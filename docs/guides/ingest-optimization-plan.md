# 摄取模块优化方案（不影响现有摄取功能）

> 适用范围：本仓库 `src/` 源码（实际运行实例在 F 盘的 ruflo-kb 项目，部署时同步即可）。
> 原则：所有优化放在摄取核心链路**之外**或做**纯增量**，保证 wiki 页面产出行为完全不变。

> ⚠️ **实现前必读 —— 代码校验发现的修正（2026-08-10）**
> 初版方案直接 `emit(EventName.PROCESSOR_DONE)` 是**严重 bug**：`src/orchestrator/orchestrator.py:52` 订阅了该事件，其 `_on_processor_done` 会调用 `run_hard_audit(payload.note_path)` 并把任务标记为 REJECTED。`PROCESSOR_DONE` 是**编排器审核流水线的专属事件**，不是 UI 进度事件。若用它做进度，会触发硬审核、可能拒绝已生成的笔记，直接违反红线。
> 修正办法：**新增一个与编排器解耦的专用进度事件**（如 `INGEST_STAGE`），只让 `ingest_tracker` 订阅。
> 其余已校验确认的事实：
> - `run_ingest` 返回 `list[WikiPage]`（见 `ingest.py:890 return pages`），**WikiPage 没有 `.path` 属性**（`wiki/core/types.py:38` 字段为 id/title/type/.../tags），归档必须用 `page_path_for(paths, page.type, page.id)` 反推磁盘路径。
> - 项目配置里**没有 `auto_archive` 字段**：`get_project()` 返回注册表条目 dict（id/name/path/last_opened/schema_version），需新增配置落点。
> - `hybrid_search(query, top_k, paths)` **没有 `mode` 参数**；`services/search.py` 也只把 `mode` 透传、不传给检索层（注释明确 "not honoured"）。所以 T3 比初版描述的改动面更大。
> - `mode=keyword` 当前**不会**白烧额度：`hybrid_search` 在 `get_embedding_provider()` 抛错时 `provider=None` 直接跳过 embed（hybrid_search.py:116-119）。省额度收益只在 T5/T7 启用 embedding 后才成立。
> - 当前 WebUI 路径下 **COLLECTOR_DONE 也不会发**（`stages/collector.py` 的 CollectorStage 不 emit，全库唯一 emit 在 `collector.py:305` 的旧采集器，用于程序化路径），故 collector 徽章目前也是暗的，T1 需一并补。
> - `PATCH /projects/{project_id}/reviews/{review_id}` 与 `POST /queue/pause`、`/queue/resume` **路由均存在**（T9 只需前端按钮）。

## 0. 目标与不可破坏红线

### 目标
1. 提升摄取可观测性（进度阶段徽章、真实百分比）
2. 节省 embedding 额度（搜索 `mode` 分流，启用 embedding 后见效）
3. 提升搜索性能（关键词缓存/索引）
4. 打通语义检索（守卫式自动 archive，P0）
5. 进度/状态持久化与配置可视化

### 不可破坏的摄取核心链路
```
CollectorStage → run_ingest(Analyzer/Generator → Fix D/E → 反向关系 → AtomicContext 原子写盘) → queue_service.update_status(APPROVED)
```
任何改动不得改变这条链路产出的 wiki 页面（文件数、frontmatter、正文内容）行为，也不得让 ingest task 因 archive/进度事件而变成 FAILED/REJECTED。

### 红线
- 禁止 emit 编排器专属事件（`PROCESSOR_DONE` / `LIBRARIAN_DONE` 的语义由编排器定义）；UI 进度用**专用解耦事件**。
- archive 失败 / embedding 未配置 → **绝不能**让 ingest task 变 FAILED，wiki 必须照常产出。
- 默认关闭自动 archive，需用户显式开启。

## 1. 风险分级

| 等级 | 项 | 说明 |
|---|---|---|
| 零风险（纯增量） | T1 进度事件(解耦版)、T2 百分比、T4 关键词缓存 | 只加事件/只改搜索层，不碰写盘与编排器 |
| 需守卫 | T5 自动 archive | 默认关 + 独立 try/except，失败即跳过，绝不 FAILED |
| 搜索层改造 | T3 mode 分流、T8 hits 回填 | 改 `hybrid_search` + `search_service`，独立于摄取 |
| 独立模块 | T6 tracker 持久化、T7 配置 UI、T9 死接口暴露 | 不改摄取逻辑 |

## 2. 阶段一：零风险快赢（可独立提交）

### T1 补全进度阶段事件（**解耦版，已修正**）
- **改动 1 — collector 阶段：无需改（2026-08-10 实现时核实）**：`collect()`（`src/pipeline/collector.py:305`）在采集成功后**已经** emit `COLLECTOR_DONE`；而 `CollectorStage.run()` 通过 `src/pipeline/__init__.py:159` 的兼容层（`pipeline.collect` → `collector.collect`）调用它，因此生产路径**本来就会**发该事件，collector 徽章已能点亮。故**不要在 `CollectorStage` 重复 emit**（会导致重复 "collector" 徽章）。安全依据：`orchestrator` **不**订阅 `COLLECTOR_DONE`（只订阅 PROCESSOR_DONE/LIBRARIAN_DONE），仅 `ingest_tracker` 订阅 + `orchestrator/state_machine.py` 把它映射为 RUNNING，纯进度/状态。
- **改动 2 — processor 阶段（关键修正）**：**不要** emit `PROCESSOR_DONE`。在 `src/events/events.py` 的 `EventName` 新增专用事件：
  ```python
  INGEST_STAGE = "ingest:stage"
  ```
  在 `src/pipeline/service.py` 的 `run_for_collector_start` 内、`run_ingest` 成功且 `update_status(APPROVED)` 之前/之后，发：
  ```python
  from ..events.events import EventName
  event_bus.emit(EventName.INGEST_STAGE, {"task_id": task_id, "stage": "processor"})
  ```
  在 `src/server/ingest_tracker.py` 新增**容忍 dict/对象**的 handler 并订阅（**不**触碰 `PROCESSOR_DONE`/`LIBRARIAN_DONE` 的现有订阅）：
  ```python
  def _on_ingest_stage(p):
      tid = p.get("task_id") if isinstance(p, dict) else getattr(p, "task_id", None)
      stage = p.get("stage") if isinstance(p, dict) else getattr(p, "stage", None)
      if not tid or not stage:
          return
      with _lock:
          rec = _tasks.get(tid)
          if rec is None:
              return
          if rec["status"] == "queued":
              rec["status"] = "running"
          rec["stages"].append({"name": stage, "at": _now_ms()})
  event_bus.on(EventName.INGEST_STAGE, _on_ingest_stage)
  ```
- **为什么安全**：专用事件与编排器审核完全解耦，`run_hard_audit` 不会被触发；纯进度记录。
- **验证**：摄取 1 篇 → 前端进度面板 collector + processor 徽章依次亮起；且 ingest task 状态始终 succeeded（不被 REJECTED）。
- **回滚**：删除两处 emit + 新增 handler/订阅。

### T2 进度百分比按真实阶段数插值
- **改动**：`web/js/views/ingest.js` 按 `rec.stages.length`（0→5%, 1→35%, 2→70%, 3→100%）设进度条宽度，替换写死的 5%/30%/100%。
- **安全**：纯 UI。
- **回滚**：还原。

### T4 关键词搜索缓存（性能）
- **现状**：`hybrid_search._keyword_search` 每次 `knowledge_dir.rglob("*.md")` + `file.read_text` 全量扫描。
- **改动**：首次搜索把 `(slug → 正文文本)` 缓存到模块级 dict（或落盘 `.index/kw_cache.json`），按文件 mtime 失效；扫描前先比对 mtime。须保留现有 `skip_parts = {"_archive","_stubs","index.md","log.md"}` 过滤。
- **安全**：只改搜索层。
- **回滚**：删除缓存逻辑，恢复 rglob。

## 3. 阶段二：守卫式自动 archive（P0，价值最大）

### T5 自动 archive（带开关 + 守卫，**已修正**）
**核心思路**：在 `run_ingest` 成功、`update_status(APPROVED)` 之后，可选地**逐页**跑 `librarian.archive`，用开关 + **独立 try/except**（绝不冒泡到外层会标记 FAILED 的 except）把风险隔离在摄取核心之外。

- **配置落点（必做子任务）**：项目配置无 `auto_archive`。二选一：
  - (A) 扩展 `src/project/registry.py` 的 `ProjectRegistryEntry` 增加 `auto_archive: bool = False` 字段并纳入 `to_dict()` + 提供更新方法；或
  - (B) 用每项目配置文件（参考 `cli_ext/relations_cmd.py` 的 `_settings_path()` 模式）存 `{"auto_archive": false}`。
  读取处一律 `cfg.get("auto_archive", False)`，缺字段默认 false，保证旧配置不报错。
- **改动点**：`src/pipeline/service.py` 的 `_run_for_collector_start_inner`，在 `run_ingest` 返回后：
  ```python
  pages = await _pipeline_mod.run_ingest(paths=paths, source_path=..., source_text=..., provider=provider, task_id=task_id)
  self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
  # —— 守卫段开始（独立 try，绝不冒泡）——
  try:
      from ..services.projects import get_project
      cfg = get_project(project_id) or {}
      if cfg.get("auto_archive", False):
          from ..pipeline.librarian import archive
          from ..wiki.core.paths import page_path_for   # 确认导入路径
          pages_list = pages if isinstance(pages, list) else [pages]
          for page in pages_list:
              try:
                  note_path = page_path_for(paths, page.type, page.id)
                  await archive(task_id=task_id, note_path=str(note_path), paths=paths)
              except Exception as e:
                  _logger.warning("auto_archive skipped page %s: %s", getattr(page, "id", "?"), e)
  except Exception as e:
      _logger.warning("auto_archive disabled/failed for %s: %s", task_id, e)
  # —— 守卫段结束 ——
  ```
- **守卫清单（关键）**：
  1. 上面整段包在**独立 try/except** 内，且位于 `update_status(APPROVED)` **之后**，因此 archive 的任何异常（含 `get_embedding_provider()` 抛 RuntimeError）都被吞掉，task 已是 APPROVED，不会被外层 `except`（service.py:134，会标 FAILED）捕获。
  2. `archive` 内部 `get_embedding_provider()` 未配置 → 抛 RuntimeError → 被本段捕获 → wiki 不变。
  3. `page_path_for(paths, page.type, page.id)` 反推每篇笔记磁盘路径（WikiPage 无 `.path`）。
  4. **不要**在此处 emit `LIBRARIAN_DONE` 以外的编排器事件；`archive` 自身会 emit `LIBRARIAN_DONE`（librarian.py:125），编排器会借此把它的任务标 ARCHIVED——属不同任务存储，需确认不与 WebUI tracker 的 succeeded 冲突（验证项）。
- **默认行为**：
  - `auto_archive=False`（默认）→ 与现在完全一致，语义检索仍不可用，摄取零变化。
  - `auto_archive=True` + embedding 已配（app.py 已 `set_embedding_provider`）→ 摄取后 LanceDB `chunks` 表有数据，语义检索可用。
  - `auto_archive=True` + embedding 未配 → wiki 正常生成，archive 静默跳过。
- **验证**：
  1. 默认关：摄取 N 篇，对比 `wiki/` 产出与改动前 git diff 完全一致；`chunks` 表仍空；task 状态 succeeded（非 REJECTED/FAILED）。
  2. 开 + embedding 配：摄取后 `list_tables()` 含 `chunks` 且有行；`POST /search mode=vector` 有结果。
  3. 开 + embedding 不配：摄取成功，task succeeded，无 archive 数据，无报错。
- **回滚**：把 `auto_archive` 设回 false 即完全回到现状。

### T5 实现修正（2026-08-10 落地时确认）
1. **配置落点改用 `paths.llm_wiki / "ingest_settings.json"`**（不扩展 `ProjectRegistryEntry`）。新增模块 `src/pipeline/auto_archive_config.py` 的 `is_auto_archive_enabled(paths)` 直接读已解析好的 `paths.llm_wiki` 目录，缺文件/缺字段/损坏 JSON/非 dict 一律默认 `False`。比方案初版写的 `get_project(project_id)` 更解耦、更低风险（不碰全局注册表数据模型，无需 migration）。开启方式：在该文件写入 `{"auto_archive": true}`（后续可由 T7 设置页写入）。
2. **`run_ingest` 返回值必须赋给 `pages` 变量**：原代码是裸 `await _pipeline_mod.run_ingest(...)`（未赋值），守卫段需改成 `pages = await ...` 才能逐页归档。
3. **stub 页也走 `page_path_for`，不是 `page_path_for_stub`**：`run_ingest` 内所有页（含 stub）都经 `write_page` → `page_path_for(paths, page.type, page.id)` 写盘；stub 的 `type=PageType.ENTITY`（`ingest.py:829`），`grade="C"`。因此守卫段用 `page_path_for(paths, page.type, page.id)` 反推路径与写入**逐字节一致**，`page_path_for_stub` 反而不匹配（stub 不在 `wiki/_stubs`）。
4. **`archive` 会 emit `LIBRARIAN_DONE`（既有行为）**：开启 auto_archive 后，该事件被 `ingest_tracker` 订阅，进度面板会额外点亮一枚 `librarian` 徽章（增益，不与 task 的 `succeeded` 冲突，因 tracker 只 append stage 不改 status）。
5. **当前 F 盘实例的硬约束**：`app.py` 启动**未**初始化 embedding provider（`get_embedding_provider()` 直接 raise）。故即便 `auto_archive=true`，`archive` 会因无 embeddings 抛 `RuntimeError` 而被守卫段吞掉——wiki 照常生成、语义检索仍空。要真正救活语义检索，**必须同时做 T7**（设置页配置 embedding provider + `app.py` 启动 `set_embedding_provider`）。T5 只是把"archive 自动触发"打通；embedding provider 可配是根因。

## 4. 阶段三：搜索层改造与 UI 收尾（独立）

### T3 搜索 mode 真正分流（**已实现**）
- **现状**：`hybrid_search(query, top_k, paths)` **无 `mode` 参数**；`services/search.py` 只把 `mode` 透传、不传给检索层（注释 "not honoured"）。当前无 provider 时本就跳过 embed，故不存在"白烧额度"。
- **改动**：
  1. `hybrid_search` 增加 `mode: str = "hybrid"` 参数；在语义段按 `mode in ("hybrid","vector")` 决定是否 embed，在关键词段按 `mode in ("hybrid","keyword")` 决定是否扫描。
  2. `services/search.py` 把 `mode` 传给 `hybrid_search(query, top_k=top_k, paths=paths, mode=mode)`。
- **注意**：`mode="vector"` 且无 provider 时当前返回空（语义结果为 []），这是既有行为；如需更友好可在无 provider 时降级关键词，但属语义微调，默认保持。
- **安全**：纯搜索层，与摄取无关。
- **回滚**：还原参数与分支。
- **已实现（2026-08-10）**：`hybrid_search` 已加 `mode` 参数并按上述分支执行；`services/search.py` 透传；前端 `web/js/views/search.js` 新增 mode 分段选择器（混合/关键词/语义）并写入请求 body。受管 Python 微验证：bad mode 抛 ValueError、keyword 模式跳过 embed 调用、vector 模式无 provider 返回空（无关键词兜底）均通过。

### T8 tokenHits / vectorHits 回填（**已实现**）
- **现状**：`services/search.py:72-73` 硬编码 0。
- **改动**：在 `search()` 返回前统计 `results` 中 `source=="keyword"` 与 `source=="semantic"` 的数量填入 `tokenHits`/`vectorHits`（SearchResult 已有 `source` 字段）。
- **安全**：纯搜索层。
- **已实现（2026-08-10）**：统计在 page_type 过滤之后进行（反映用户实际所见）；`node --check` 通过。前端 search.js 本就读取这两个字段渲染命中数（此前恒 0 不显示），现在会真实展示。

### T6 ingest_tracker 持久化（**已实现**）
- `src/server/ingest_tracker.py` 内存 dict → 落盘 `.index/ingest_tracker.json`（默认存储目录，支持 `init_tracker(storage_dir=...)` 覆盖），`init_tracker` 时 `_load_from_disk()` 回填；每次 `_on_created/_on_status/_on_dead_letter/_touch_stage/_append_stage/prune_finished` 变更后 `_persist()` 用 `safe_write` 原子写。最佳努力：任何持久化失败仅 warning，不影响摄取。避免重启后 `GET /ingest/status/{id}` 返回 404。
- **已实现（2026-08-10）**：受管 Python 加载真实模块验证——创建任务后落盘 queued、状态变更后落盘 succeeded、重新 init_tracker 能从磁盘恢复任务，全部通过。

### T7 让语义检索真正初始化的最后一公里（**已实现**）
> **真实根因（代码级，推翻初版"只加 UI"假设）**：`app.py` 的 lifespan **已经**写了 embedding 初始化（`get_default()` → `create_embedding_provider` → `set_embedding_provider`，app.py:92-113）。但当默认 provider 的 `type=="openai-compatible"`（当前 MiniMax 被前端存成了这个 type）时，`create_embedding_provider` 第 89 行 `raise ValueError("Unknown embedding provider: openai-compatible")` → 被 except 吞成 warning → **embedding 永不初始化**。叠加前端 `settings.js:271` 把 chat 模型名（`MiniMax-Text-01`）当 embedding 模型塞进 `default_embedding_model`（`embedding_model: model`），双重失效。MiniMax embedding 走专用协议（`embo-01`，需 `texts` 字段、返回 `vectors`，非 OpenAI 兼容），必须用 `MiniMaxEmbeddingProvider` 适配器——这才是根因核心。

**改动（全部纯增益，不影响摄取）**：
- **T7-A `src/llm/provider_factory.py`**：`create_embedding_provider` 的 `provider in ("openai", "openai-compatible")` 走同一 OpenAI 分支（支持自定义 endpoint+model），覆盖 Kimi/DeepSeek/GLM 等 OpenAI 兼容 embedding。minimax/ollama 分支不变。
- **T7-B `src/server/app.py` lifespan**：embedding 初始化增加类型兜底——`"minimax" in base_url.lower()` → 强制 `type="minimax"` + `model="embo-01"`（专用适配器）；`type=="openai-compatible"` → 映射 `openai`；其余原样。保持 `except` 仅 warning、**不阻断启动**。
- **T7-C `web/js/views/settings.js`**：`PROVIDER_PRESETS` 增加 `embedding_model` 字段（minimax→`embo-01`、openai→`text-embedding-3-small`、glm→`embedding-3`、其余留空）；modal 增加"Embedding 模型"独立输入框；提交时 `chat_model` 与 `embedding_model` 分开传（不再混填 chat 模型名）。
- **后端已具备、无需改**：`POST /providers` 的 `AddProviderRequest` 本就有 `embedding_model` 字段（`providers.py:31`），且 `default_embedding_model = body.embedding_model or body.chat_model`；`ProviderConfig.default_embedding_model` 字段 to_dict/from_dict 对称（types.py:65/82）。

**验证**：4 个改动文件 `py_compile` 全过；`node --check` 过 JS；受管 Python 用 importlib 加载**真实** `provider_factory.py`（桩入 openai_provider/minimax_embed 等子模块）验证分发——`openai`→`text-embedding-3-small`、`openai-compatible`→传入 model、`minimax`→`embo-01`、未知类型仍 `raise ValueError`（无回归）全 OK。**完整 pytest 仍因沙箱缺 httpx/yaml 未能跑**，建议本机 `uv run pytest tests/test_server/ tests/test_llm/` 确认。**端到端"真能嵌入"需本机有效 api_key + 联网**，沙箱不可验。
**回滚**：T7-A 把 `in (...)` 改回 `== "openai"`、T7-B 删类型兜底、T7-C 删 embedding 输入框即回现状；默认 provider 未配 embedding 时行为与改动前一致（warning 不初始化）。
**生效条件**：F 盘 ruflo-kb 实例需 (1) 同步本源码 (2) 在设置页把 MiniMax 的 Embedding 模型填为 `embo-01` 后保存 (3) 重启服务，语义检索才会真正可用（配合 T5 的 auto_archive 开关）。

### T9 暴露已有死接口（**已实现**）
- 前端加：reviews「解决/驳回」按钮 → `PATCH /api/v1/projects/{project_id}/reviews/{review_id}`；队列 `pause/resume` 按钮 → `POST /api/v1/queue/pause`、`/queue/resume`（后端路由均已存在）。
- **已实现（2026-08-10）**：`web/js/views/status.js` 新增队列「暂停/恢复」按钮与状态 pill（读 `GET /api/v1/queue/status`）；状态页新增「待审核」卡片渲染 reviews 列表（每条带「解决」/「驳回」按钮，分别 PATCH `{resolved:true,action:"skip"}` 与 `{resolved:false}`，成功后自动刷新）。此前 reviews 仅显示计数、队列控制死接口前端未接。`node --check` 通过。

## 5. 总体验证策略
- 每个阶段后用 `python -m pytest --import-mode=importlib` 跑全量测试，保持全绿（现有 873 测试）。
- 摄取一致性：阶段一/二改动后，跑单篇 + 批量摄取，用 `git diff wiki/` 确认页面产出与改动前字节级一致（核心链路未被改）；并确认 task 状态非 REJECTED/FAILED。
- 语义检索：T5 开启后，`POST /search` 的 `mode=vector` 与默认 hybrid 应返回非空。
- 回归：确认 emitting `INGEST_STAGE`（而非 `PROCESSOR_DONE`）后，`orchestrator._on_processor_done` 不再被摄取流程触发（可在摄取后查任务未进入 REJECTED）。

## 6. 建议执行顺序
`阶段一(T1→T2→T4)` → `阶段二(T5)` → `阶段三(T3→T8→T6→T7→T9)`

## 7. 风险与回滚总表
| 项 | 风险 | 回滚 |
|---|---|---|
| T1（解耦版） | 极低（专用事件，不碰编排器） | 删 emit/handler |
| T2 | 零（UI） | 还原 |
| T4 | 低（搜索层） | 删缓存 |
| T5 | 中（需守卫+配置落点） | auto_archive=false 即回现状 |
| T3 | 低（搜索层，改动面略大） | 还原参数与分支 |
| T8 | 低（搜索层） | 还原 |
| T6 | 低（加存储） | 还原内存态 |
| T7/T9 | 低（独立） | 还原 |

> 实施备注：
> 1. T1 的 processor 阶段**必须**用新增的 `INGEST_STAGE` 专用事件，绝不可复用 `PROCESSOR_DONE`（会触发 `orchestrator.run_hard_audit` → 可能 REJECT）。
> 2. T5 的 `note_path` 必须用 `page_path_for(paths, page.type, page.id)` 反推；`run_ingest` 返回 `list[WikiPage]`，逐页归档。
> 3. T5 的 archive 调用必须位于 `update_status(APPROVED)` **之后**且包在**独立 try/except** 内，确保异常不触达会标记 FAILED 的外层 except。
> 4. T3/T8 是搜索层改造，独立于摄取，可单独评审。
