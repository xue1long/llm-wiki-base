# 跨机器交接 Runbook —— V7 摄取管线 Stage 1 灰度观察

> 适用范围：把 V7 摄取管线的 Stage 1 灰度观察与质量门验收交给另一台机器的 agent 执行。
> 所有命令从仓库根目录运行。原始执行机器（下称「源机」）因 MiniMax API 持续 429 限流被阻塞，
> 换机器可换出口 IP / 配额，是本次交接的直接动机。

---

## 1. 交接目标

远端 agent 需要完成三件事，按优先级排列：

| 编号 | 工作项 | 依赖 | 产出 |
|---|---|---|---|
| **A** | 复现 V7 桥接冒烟，确认链路在干净机器上可用 | 仅需 provider 可用 | `scripts/smoke_v7_bridge.py` 的 PASS + report JSON |
| **B** | Stage 1 灰度观察（3 天，用户已定） | A 通过 | 每日摄取记录 + H1–H5/wiki-quality 结果 |
| **C** | 质量门修复计划 Task 6：隔离实例真实 smoke | 独立于 A/B | 隔离项目目录下的验收结果 |

**明确不在本次范围内**（属于 Stage 2/3，源机保留决策权）：

- 改 `RUFLO_PIPELINE_MODE` 的默认值（Stage 2）
- 删除 candidate / chunked / unified 旧路径代码（Stage 3）
- 任何对 `src/pipeline/v7_extract/` 的架构性改动

---

## 2. 前置：仓库与环境

```bash
git clone https://github.com/xue1long/llm-wiki-base.git
cd llm-wiki-base
git checkout codex/book-series-target
git rev-parse --short HEAD      # 交接基线，见本文档末尾
```

环境安装的四类坑（Python 3.14 wheel、代理绕过、嵌套 conftest 级联）**不在本文重述**，
按 [`docs/environment/SETUP.md`](../environment/SETUP.md) 走。要点：

- `pip install -e ".[dev]"`，本机代理会拖死大 wheel，需按 SETUP.md §2 绕过代理。
- **不要跨机器复制 `.venv/`**：`pyvenv.cfg` 里的 `home` 是机器绝对路径，
  源机上就因为 home 指向错误的 `C:\Python314` 而报错。远端重新建 venv。
- 跑测试必须带两个参数，否则 collection 直接失败：

  ```bash
  PYTHONPATH=. python -m pytest --import-mode=importlib
  ```

---

## 3. 前置：LLM provider 配置（手动步骤，密钥不入库）

provider 配置在仓库外的 `~/.config/ruflo-kb/llm-providers.json`，
且该文件名已被 `.gitignore` 排除。**密钥不通过 git 传输**，由用户用安全渠道交给远端。

远端执行（MiniMax 示例，openai-compatible 端点没有环境变量自动映射，必须显式传 key）：

```bash
python -m src.cli llm-providers add minimax openai-compatible \
  --base-url  "$MINIMAX_BASE_URL" \
  --model     "$MINIMAX_CHAT_MODEL" \
  --api-key   "$MINIMAX_API_KEY"
python -m src.cli llm-providers set-default minimax
```

配置完成后先自检，确认 key 与 endpoint 可用、且**当前没有 429**：

```bash
python -m src.cli llm-providers list
python -X utf8 scripts/smoke_v7_bridge.py --no-commit
```

备用 provider：`RUFLO_LLM_PROVIDER=ollama`（本地、无限流，但源机上 Ollama 502 不可用，
需先确认远端 Ollama 状态）。

---

## 4. 前置：项目种子（已在仓库内）

`knowledge/novel-wiki-v2/` 的**可复现种子**已入库，远端 clone 后即可用：

| 内容 | 路径 | 说明 |
|---|---|---|
| 固定项目 ID | `.llm-wiki/project.json` | `9be6839c-3a38-43e2-88cf-0fdb37fe3e1c`；为使命令可直接复制，已加 `.gitignore` 白名单 |
| schema / purpose | `schema.md`、`purpose.md` | 摄取时被 pipeline 读取，决定类型与槽位 |
| taxonomy | `taxonomy.md`、`taxonomy_tags.md` | `extract_relations` 依赖 |
| 页面模板 | `.wiki-templates/*.md`（5 个） | `concept.md` 的 8 个槽位与 V7 `ConceptPage` 一一对应 |
| 源文档 | `raw/sources/`（133 文件，3.84 MB） | 含标准靶子 `视频音频转录教程/音频教程/大纲写作技巧.md` |
| Book 规则 | `book.rules.md` | Task C 的 book 验收需要 |

**没有入库、需要远端自行生成**（属运行态产物，不应跨机器搬运）：

- `wiki/`（生成的页面、`index.md`、`log.md`）
- `.index/`（LanceDB 向量、`kc/` bundles、`quarantine/`、`page_versions/` 等）

标准靶子源文档指纹（用于确认两边喂的是同一份输入）：

```
raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md
26,398 字符 / 70,966 字节 / md5 28ca27726c9c2ec834c47eb5470cf555
```

它是 V7 替换工作的 worst-case 源——旧 candidate 路径正是在这份文档上失败的。

> **口径提醒**：上面的 md5 是**解码后文本**（universal newlines，`\r\n` 已归一为 `\n`）
> 的 md5，由 `smoke_v7_bridge.py` 算出并写进报告。仓库没有对 `.md` 钉死 `eol`
> （`.gitattributes` 只约束 `*.bat`），而 `core.autocrlf` 在对端可能为 `true`，
> 于是 checkout 后文件的**物理字节数可能不同**。所以：
> - ✅ 用脚本输出的 `source_md5` / `source_chars` 对指纹——脚本用
>   `Path.read_text()` 读，自动归一换行，两端一致；
> - ❌ 不要用 `certutil -hashfile` 之类对原始字节取 md5 来比对，CRLF 检出会误报不一致。

### 4.1 首次落地：建目录骨架

clone 之后 `wiki/` 与 `.index/` 不存在。启动一次服务器即可建全
（`src/server/app.py:153` 在 lifespan 里按 `--project-root` 调
`ensure_knowledge_base`，幂等，且不会改 `project.json`）：

```bash
python -X utf8 -m src.cli serve --host 127.0.0.1 --port 19828 \
  --project-root knowledge/novel-wiki-v2
# 等到 /health 返回 ok 后 Ctrl-C
```

`wiki/index.md` 与 `wiki/log.md` 不必预置——`append_to_index`
（`src/wiki/features/indexer.py:43`）在文件缺失时会用内置表头自建。

**不要用 `project init` 重建项目**：那会生成新的 `project.json` 与新 UUID，
本文档中所有命令里的 `9be6839c-...` 就会失效。

---

## 5. 工作项 A：复现 V7 桥接冒烟

```bash
# 最快：只跑桥接不写盘，约 30 秒，5 次 LLM 调用
python -X utf8 scripts/smoke_v7_bridge.py --no-commit

# 完整：写盘 + health + wiki-quality --strict
python -X utf8 scripts/smoke_v7_bridge.py
```

脚本默认参数即标准靶子；可覆盖：

```bash
python -X utf8 scripts/smoke_v7_bridge.py \
    --project-root knowledge/novel-wiki-v2 \
    --source "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md" \
    --provider minimax \
    --max-usd 1.0 --max-calls 30 --stage-timeout-sec 180
```

- 退出码 0 = 通过；1 = 失败。
- 报告写到 `.tmp-smoke-v7-report.json`（含 `source_md5`、`elapsed_sec`、
  `llm_calls`、`failure_stage`、`health_exit`、`wiki_quality_exit`），
  日志同时打印并追加到 `.tmp-smoke-v7.log`。
- `--v3` 走 `fill_slots_v2`（v3）路径：**调用数约 9 倍**，2 个 topic 就会顶到
  20 次预算上限并 abort。只在显式抬高 `--max-calls` 时使用。

**预期通过基线**（源机实测，v2 路径）：

| 指标 | 期望值 |
|---|---|
| 耗时 | 约 21 秒（HTTP 路径）／26–40 秒（直连桥接） |
| LLM 调用 | 5 |
| 页数 | 1 source stub（约 1.6 KB）+ 1 concept（约 9.6 KB） |
| H1–H5 | 0 issue / HEALTHY |
| `wiki-quality --strict` | HEALTHY（0 error；重复摄取同一源会有 1 条 duplicate-title warning） |
| 成本 | 约 $0.05 |

---

## 6. 工作项 B：Stage 1 灰度观察（3 天）

### 6.1 启动服务器

```bash
RUFLO_PIPELINE_MODE=v7 \
RUFLO_LLM_PROVIDER=minimax \
python -X utf8 -m src.cli serve \
  --host 127.0.0.1 --port 19828 \
  --project-root knowledge/novel-wiki-v2
```

启动约需 30 秒（本地 embedding 模型加载）。确认就绪：

```bash
curl -s http://127.0.0.1:19828/health
curl -s http://127.0.0.1:19828/ready
```

服务日志里出现 `[v7-bridge]` 标记即表示 V7 路径已激活。

### 6.2 摄取

```bash
curl -X POST \
  http://127.0.0.1:19828/api/v1/projects/9be6839c-3a38-43e2-88cf-0fdb37fe3e1c/ingest \
  -H "Content-Type: application/json" \
  -d '{"source": "raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md"}'
```

`source` 用**相对项目根**的路径（源机实测可用，便于跨机器复制）。
绝对路径亦可。返回 `{status, taskId}`，处理是异步的。

### 6.3 查任务结果

```bash
# 单任务状态（路由见 src/server/routes/ingest.py:80）
curl -s "http://127.0.0.1:19828/api/v1/projects/9be6839c-3a38-43e2-88cf-0fdb37fe3e1c/ingest/status/<taskId>"

# 该项目全部摄取任务（最近的在前）
curl -s "http://127.0.0.1:19828/api/v1/projects/9be6839c-3a38-43e2-88cf-0fdb37fe3e1c/ingest/tasks"
```

队列整体状态：`curl -s http://127.0.0.1:19828/api/v1/queue/status`

### 6.4 每日观察记录

每天至少跑一轮，逐条记录：

```bash
python -m src.cli health       --project 9be6839c-3a38-43e2-88cf-0fdb37fe3e1c
python -m src.cli wiki-quality --project 9be6839c-3a38-43e2-88cf-0fdb37fe3e1c --strict
python -m src.cli lint         --no-cache --project 9be6839c-3a38-43e2-88cf-0fdb37fe3e1c
```

**通过判据**（3 天内全部满足才可进 Stage 2）：

1. 任务状态为 `succeeded`，且**确实写入了页面**——不允许「`succeeded` 但 0 页面」。
2. H1–H5 = 0 issue。**注意 H2（unresolved 引用）目前会平凡通过**——V7 产出的
   concept 页根本没有关系边，H2=0 不能当作引用质量合格的证据。详见 §9 坑 7。
3. `wiki-quality --strict` 无 error。
4. 同一源重复摄取不产生第二个 source 页、不产生重复 concept。
5. 失败时必须体现为 `failed`（含完整 error message 与 `retry_count`），
   而不是被静默记为成功。

第 5 条是已修 bug 的回归护栏，见 §9 坑 1。

---

## 7. 工作项 C：质量门修复计划 Task 6

计划：`docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair.md`（§Task 6）。
进度台账：`.superpowers/sdd/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair/progress.md`。
Task 1–5 已完成，**只剩 Task 6**。

要求（计划原文）：

1. 用**临时项目目录**套 `novel` 模板，复制一份代表性 source，跑真实单文档摄取。
   **不得覆盖 `knowledge/novel-wiki-v2/wiki/` 的实测结果。**
2. 检查 `wiki/index.md`、`wiki/log.md`、`.index/quarantine/`、gap ledger 与生成页面。
3. 跑验收命令：

   ```bash
   python -m src.cli lint         --no-cache --project <temp-project>
   python -m src.cli tags validate --all     --project <temp-project>
   python -m src.cli wiki-quality  --project <temp-project> --strict
   python -m src.cli book show     --project <temp-project> --json
   python -m src.cli book build    --project <temp-project> --json
   python -m pytest --import-mode=importlib tests/test_e2e/test_ingest_happy_path.py -q
   ```

4. 验收标准：页面数为 3（1 source + 2 concept）；lint 无 `INVALID-PROCESSING-DEPTH` /
   `MISSING-SECTION` / placeholder 错误；H2 真实 unresolved 普通引用为 0（合法 taxonomy
   不计为 broken link）；quality gate 不因 source/concept 同名失败；第二次摄取同一 source
   不产生重复 page/gap/bundle；Book dry-run/build 只见最终实际发布的对象；
   ASR 噪声与 provenance 缺失仍以内容告警呈现。

基线快照（修复前的 KC bundle + wiki 页面 + publication/gap 状态）在
`.superpowers/sdd/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair/before/`，可用于前后对比。

完成后把 `progress.md` 的 `Task 6: todo` 改成完成记录（含 commit 号与实测数字）。

---

## 8. 回写约定

远端每完成一项，按仓库既有约定留痕：

| 内容 | 写到哪 |
|---|---|
| 观察/排查/踩坑记录 | `.memory/feedback-v7-replace-stage1-<远端标识>-<日期>.md`，并在 `.memory/MEMORY.md` 建索引 |
| Task C 完成 | `.superpowers/sdd/2026-09-18-.../progress.md` 台账 |
| 计划状态变化 | 对应 `docs/superpowers/plans/*.md` |

注意：`.memory/` 被 `.gitignore` 排除，新增文件需 `git add -f`（仓库既有做法）。

提交信息格式：`type(scope): 中文描述`（`feat|fix|refactor|docs|test|chore`），
**不要 `git add .`**。推送前先问用户。

---

## 9. 已知坑与边界

1. **「成功但 0 页面」已修，别改回去。** 源机上 V7 分支曾在 `failure_stage` 非空时
   返回空页面而不抛异常，队列因此把失败记为 `succeeded`。现已按瞬时性分类抛异常：
   `stage1` / `budget` / `timeout` / `unhandled` → `RetryableDependencyError`（重试 3 次后
   dead_letter）；`stage3_incomplete` / `stage4_empty` / `stage5_v2_not_implemented` →
   `InvalidInputError`（立即 dead_letter）。回归测试覆盖在
   `tests/test_pipeline/test_v7_extract_bridge.py`。
2. **`RUFLO_V7_STAGE_TIMEOUT_SEC` 必须是整数。** `BridgeBudget.from_env()` 用 `int()`
   解析，传 `"180.0"` 会 `ValueError`。
3. **v3 路径成本是 v2 的 9 倍。** 2 topic × 9 calls + 5 fixed = 23 calls，超过默认
   20 上限就 abort（写 `v7_failure.md` 到 quarantine，0 副作用）。多 topic 源会频繁触发，
   需要时抬高 `RUFLO_V7_MAX_CALLS`（建议 30）或降低 v7 内部重试。
4. **MiniMax 429 会放大。** `classify_doc` 是 3 次重试 × 4 次内部尝试 = 12 次调用，
   限流时全部耗尽。源机从 2026-09-19 11:44 起持续 429。若远端同样 429，
   考虑换 provider 或降低 `max_retries`。
5. **`BridgeBudget.from_env()` 读的是环境变量，不是函数参数。**
   直接调 `run_v7_ingest` 时若 `budget=None`，会从 env 构造预算，
   在脚本里设置 `RUFLO_V7_MAX_*` 要注意生效顺序（先设 env 再调用）。
6. **基线中已有的失败测试，不要当成本次回归**（源机确认与本次改动无关）：
   - `tests/test_analyzer_json.py::test_schema_check_missing_source_id_rejected`
   - `tests/test_pipeline.py::test_run_batch_ingest_processes_multiple_files`
   - 顺序相关的 flaky：`test_v7_extract_stage6.py`、`test_v7_extract_topic_clusterer.py`、
     `test_v7_extract_gold_corpus.py`
7. **Stage 6 关系抽取在 V7 路径上是空转的（已确认，未修）。** 三处叠加导致
   V7 产出的 concept 页 `relations: []`：

   - `bridge.py:488` 调 `extract_relations(concept_pages, llm=llm, project_root=...)`，
     **没有传 `index`**。而 `extract_relations` 的签名里 `index: Any = None`，
     文档明确写着「`index is None` 是 legacy / tests 路径」。生产本应走
     `_extract_with_ontology`（有界候选检索 + 谓词白名单）。
   - 走 legacy 分支后 `relation_extractor.py:76` → `_extract_with_llm`，其中
     `asyncio.run(response)`（line 252）在**已运行的事件循环内**会抛
     `RuntimeError`，被 `except` 吞掉 → 返回空。这正是源机一直看到的
     `RuntimeWarning: coroutine 'ProviderAdapter.complete' was never awaited`
     的来源（对端若看到同一告警，根因在此，不是测试环境噪音）。
   - 即使上面能返回结果也没用：`bridge.py:488` 是 `_ = extract_relations(...)`
     —— **返回值被丢弃**；而 `adapt_concept_page` 从不给 `WikiPage` 传
     `relations`，只有 `build_source_stub_page` 会建 `references` 边。

   **实测证据**：`knowledge/novel-wiki-v2/wiki/concepts/d237368f-raw-sources-*.md`
   的 frontmatter 是 `relations: []`；对比 candidate 路径产出的
   `wiki/concepts/小说大纲写作技巧.md`，它有 `taxonomy_of` + `references` 边。

   **影响**：(a) Stage 6 每次仍花 1 次 LLM 调用但结果无用；
   (b) V7 concept 页没有 `refines` / `supported_by` / `taxonomy_of` 边，
   基于 backlinks / relations 的导航与检索看不到它们；
   (c) **H2「unresolved 引用」可能因为根本没有边而平凡通过**——
   Stage 1 验收时不要把 H2=0 当成「引用质量合格」的证据。

   **需要用户先定方向再动代码**：是给 `extract_relations` 传 `index` 走 ontology
   路径并接住返回值，还是按其它方式落关系。属架构决策，不在本次交接的动手范围内。
8. **Stage 3 的批量删除必须合并成单个 commit**（candidate / chunked / unified 路径互有
   import 依赖），否则中途会 import 失败。这是源机留的记录，供后续参考。

---

## 10. 相关文档索引

| 主题 | 文档 |
|---|---|
| 替换方案总纲（4 阶段 rollout） | `docs/superpowers/plans/2026-09-18-v7-replace-candidate-pipeline.md` |
| 该方案的两轮审查 | 同目录 `...-audit-r1.md`、`...-audit-r2.md` |
| Stage 1 整改指南 | `docs/guides/v7-stage1-remediation.md` |
| 质量门修复计划 | `docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair.md` |
| 质量门审计 | `docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-audit.md` |
| 环境搭建 | `docs/environment/SETUP.md` |
| 领域/规范与 WebUI | `docs/guides/wiki-spec.md`、`docs/webui-buttons.md` |
| 运维 Runbook | `docs/ops/runbook.md` |
| 会话记忆索引 | `.memory/MEMORY.md` |

关键 `.memory/` 条目：

- `decision-v7-replace-grilling-2026-09-18.md` —— 六框架评估后选定「灰度 + 延迟删除」的决策依据
- `design-v7-ingest-integration-2026-09-18.md` —— 接入设计（页面必须走 `commit_ingest`，
  不走 V7 自带的 `WikiWriter`）
- `feedback-v7-replace-stage0-complete-2026-09-18.md` —— Stage 0 验收
- `feedback-v7-replace-stage1-p1-2026-09-18.md` —— 三项 P1 修复
- `feedback-v7-replace-stage1-launch-2026-09-19.md` —— Stage 1 启动实测
- `feedback-v7-replace-stage1-troubleshoot-2026-09-19.md` —— 两个 bug 的根因与修复
