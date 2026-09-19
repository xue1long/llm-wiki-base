# V7 Extract 接入生产摄取管线（替换旧的候选/旧管线）

## 1. 现状盘点

### 1.1 三条已知 pipeline（按时间倒序）

| 路径 | 入口 | 启用条件 | 现状 |
| --- | --- | --- | --- |
| **V7 extract 7 阶段** | `scripts/extract_pilot.py` + `extract_full.py` | 仅 CLI 调用 | 已 smoke-test 通真实 MiniMax-M3，但未接 ingest queue |
| **候选 (candidate) — Task 2** | `src.pipeline.ingest.run_ingest` 第 743 行 `_candidate_mode=True` | `RUFLO_PIPELINE_MODE` 默认 | **生产实际跑** |
| **旧 unified / chunked** | `src.pipeline.ingest.run_ingest` 第 884/926 行 | `RUFLO_PIPELINE_MODE=legacy` | 旧路径，弃用 |

`grep "from src.pipeline.v7_extract" src/pipeline/ingest.py` = **0 命中**。

### 1.2 V7 extract 模块完成度

| 阶段 | 函数 | 文件 | 状态 |
| --- | --- | --- | --- |
| 1. classify_doc | `classify_doc` | `doc_classifier.py` | async ✓ |
| 2. structure_recognizer | `segment_articles` | `article_segmenter.py` | async ✓ |
| 3. completeness_checker | `check_completeness` | `completeness_checker.py` | async ✓ |
| 4. topic_clusterer | `cluster_topics` | `topic_clusterer.py` | async ✓ |
| 5. slot_filler | `fill_slots` / `fill_slots_v2` | `slot_filler.py` + `page_synthesizer.py` | async ✓ |
| 6. relation_extractor | `extract_relations` | `relation_extractor.py` | sync ✓ |
| 7. wiki_writer | `WikiWriter.commit_and_index` | `wiki_writer.py` | sync ✓ |
| **orchestrator** | **不存在** | — | **缺失** |

唯一的端到端 orchestration 在 `scripts/extract_pilot.py:run_pilot` / `_extract_one`（仅 CLI）。`gold_corpus.py` 也是按 stage 跑测试。

### 1.3 V7 写入格式（关键差异）

`wiki_writer.py:552-577` 写入的 YAML frontmatter 包含 `owner: "v7"`、`pipeline: "v7"`、`pipeline_fingerprint`、`commit_id`。而候选路径写出的页面带 `_ko_extra`、`template_version`、`processing_depth: source|concept` 等。

**生产 wiki 库内有混合格式**：`knowledge/novel-wiki-v2/wiki/` 下 2 页是候选路径（v2 迁移期）写的，要切换到 V7 需要：
- V7 写入的页面前缀带 `owner: v7`
- 旧页面保留但 `owner` 缺失
- lint.py 应兼容（最新 lint 已支持 `<!-- wiki-template-version: 3.0.0 -->` 注释）

### 1.4 测试 / 烟测覆盖度

- **V7 单测**：30 个 `test_v7_extract_*.py`，含 `gold_corpus.py` 用 FakeLLMClient 跑 stage 1-7
- **真实 Provider 烟测**：`.memory/feedback-v7-control-plane-real-provider-smoke-2026-09-15.md` 单源 apply 跑通，写出 3130 bytes 概念页
- **多源全量 apply**：`extract_full.py` 4918 文件从未跑过
- **生产 raw apply**：`knowledge/novel-wiki/` 从未被 V7 触碰

### 1.5 审计结论（2026-09-17 整改 plan-audit）

`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r1-reassessment.md` 列出：

| 编号 | 等级 | 描述 | 是否阻塞接入 |
| --- | --- | --- | --- |
| F1–F3, F6, F7, F16, F17 | 旧 wiki 兼容性 | "旧 wiki 不管"决策 | **不阻塞** |
| F4 Reconciliation fingerprint 不传播 | ① 致命 | 未来系统缺陷 | 不阻塞 |
| F5 byte offset slice 切错 | ② 重大 | 已有 Task 5 修复 | 修完可上 |
| F8 Stage 6R frontmatter 冲突 | ③ 优化 | 关系不入 frontmatter | **不阻塞** |
| F9 UNCERTAIN 阈值 | ② 重大 | 已有 Task 9 | 修完可上 |
| F10 vector_neighbor | ② 重大 | Reconciliation 依赖 | 不阻塞接入 |
| F11 durable_failure vs reviews_queue 双写 | ② 重大 | 已有 Task 21 | 不阻塞 |
| F12 traits 死字段 | ② 重大 | 已有 Task 1 | 不阻塞 |

**结论**：没有 ① 致命缺陷阻塞接入。F5/F9/F11/F12/F13/F14/F15 已有 Task 编号但不一定全完成——需要验证。

---

## 2. 集成设计

### 2.1 最小入侵式集成（推荐）

不改 queue / server / collector；只在 `src.pipeline.ingest.run_ingest` 第 743 行加一个 `_v7_mode` 分支，与 `_candidate_mode` 并列。

```
[src/pipeline/ingest.py:742-745]
_v7_mode = os.environ.get("RUFLO_PIPELINE_MODE") == "v7"  # 新增
if _v7_mode:
    pages = await _v7_ingest(paths, source_path, source_text, provider, ...)
elif _candidate_mode:
    # 现有逻辑不变
    ...
```

`_v7_ingest` 调用新的桥接层 `src/pipeline/v7_extract/bridge.py:run_v7_ingest`：

```
[src/pipeline/v7_extract/bridge.py]  ← 新增
async def run_v7_ingest(
    *,
    paths: WikiPaths,
    source_path: Path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "",
) -> list[WikiPage]:
    """End-to-end V7 extraction → WikiPage list. Adapts extract_pilot._extract_one."""
    llm = _to_v7_llm(provider)
    wiki_root = paths.root

    # Stage 1
    classification = await classify_doc(source_text, ..., llm=llm, project_root=wiki_root)

    # Stage 3 (Stage 2 optional, depends on doc_type)
    complete_result = await check_completeness(source_text, classification.doc_type, llm=llm, project_root=wiki_root)

    # Stage 4
    items = []  # may use Stage 2's articles
    cluster_result = await cluster_topics(items, source_text, ..., llm=llm, project_root=wiki_root)

    # Stage 5 (per topic)
    pages: list[ConceptPage] = []
    for topic in cluster_result.topics:
        result = await fill_slots_v2(topic, ..., llm=llm, project_root=wiki_root)
        if result.fill_status == FILLED:
            pages.append(result.page)

    # Stage 6
    relations = extract_relations(pages, llm=llm)

    # Stage 7 (existing WikiWriter)
    writer = WikiWriter(root=wiki_root, content_filter=content_filter)
    report = writer.commit_and_index(pages, relations)

    # Adapt V7 ConceptPage → existing WikiPage for downstream ingest.py logic
    return [_adapt_concept_page(p, paths) for p in report.written]
```

### 2.2 必须解决的接口契约问题

#### 2.2.1 V7 LLMClient ↔ Provider 适配

V7 用 `src.pipeline.v7_extract.llm_client.LLMClient` 抽象，现有系统用 `src.llm.provider_factory.create_llm_provider`。需要 adapter：

```
[src/pipeline/v7_extract/llm_bridge.py]  ← 新增
class ProviderAdapter(LLMClient):
    """Adapt src.llm.* Provider to V7's LLMClient interface."""
    def __init__(self, provider):
        self._p = provider

    async def chat(self, *, messages, response_format=None, **kwargs):
        # Call existing provider.chat() with OpenAI-style messages
        ...
```

实测已有 `src/v7_agl/agent.py:55` 用 `BaseURLLLMClient`（import 自 `v7_extract.llm_client`），说明这个 adapter 模式在 AGL 链路里已有先例可参考。

#### 2.2.2 V7 ConceptPage ↔ WikiPage 适配

V7 输出 `ConceptPage`，下游 `ingest.py:quality_gate.check_pages` 等需要标准 `WikiPage`。需要在 `_v7_ingest` 内部完成转换：
- ConceptPage.slots → WikiPage.body（按 `_SLOT_HEADINGS` 拼装 `## {中文标题}\n{body}`）
- ConceptPage.id → WikiPage.id（直接复用）
- ConceptPage.sources → WikiPage.sources
- ConceptPage.topic_id → WikiPage.custom_type 或 tag
- ConceptPage.slot_evidence → WikiPage.frontmatter._ko_extra.evidence

#### 2.2.3 Source 页（与 concept 区分）

候选路径会同时产出 1 个 source 页 + N 个 concept 页（`generate_from_candidate` 内部）。V7 的 `commit_and_index` **不产 source 页**——只产 concept 页。这意味着切换后源文档的"摘要/可信度/关键观点"页会缺失。

**3 个备选**：
- **A** (推荐)：让 V7 bridge 在 concept 之外**额外**生成一个 source 页（复用 `WikiPage` 构造器，body 填 frontmatter + 摘要 stub）
- **B**：彻底放弃 source 页（前端用 wiki 摘要工具从 concept 页聚合）
- **C**：保留原 `_analyze` 单 source 页 + V7 多 concept 页 混合模式（半切换）

#### 2.2.4 Wiki 目录结构

候选路径用 `wiki/sources/<slug>.md` + `wiki/concepts/<slug>.md` + `wiki/entities/...`（5 类 page type）；V7 也写 `wiki/concepts/<id>.md`——但 V7 不分 type 目录，只用 page.type 字段。**需要确认现有 lint 能容忍混合格局**。

### 2.3 切换开关

| 开关 | 行为 |
| --- | --- |
| `RUFLO_PIPELINE_MODE` 未设 | 候选（现状） |
| `RUFLO_PIPELINE_MODE=candidate` | 候选 |
| `RUFLO_PIPELINE_MODE=legacy` | 旧 unified |
| **`RUFLO_PIPELINE_MODE=v7`** | **V7（新加）** |

shadow 模式：把 v7 输出写到 `.index/shadow/<task_id>/`，与候选主路径并行。**注意**：现有 `src/pipeline/shadow.py` 是 dead code（仅 legacy 对比），需要修一下。

### 2.4 Wiki 库迁移

切换需要：
1. 用 V7 dry-run 跑全量生产 raw，写 `.index/shadow/...`（不动 wiki）
2. 对比 V7 输出 vs 当前 wiki 页面 diff（slot count、长度、关键概念覆盖率）
3. **不直接覆盖现有页面**——只增量（新 source 走 V7，旧 source 保留）
4. 监控 N 周后人工 decide 是否回填

---

## 3. 实施路径（建议分 3 阶段）

### Phase 1 — 桥接层实现 + 单元测试（不切生产）

任务：
- [ ] 新增 `src/pipeline/v7_extract/llm_bridge.py:ProviderAdapter`
- [ ] 新增 `src/pipeline/v7_extract/bridge.py:run_v7_ingest` 入口
- [ ] 新增 V7→WikiPage 适配层（`_adapt_concept_page`）
- [ ] 实现 source 页 stub 生成
- [ ] 写单元测试 `tests/test_pipeline/test_v7_extract_bridge.py`：
  - ProviderAdapter 与 4 种 Provider 兼容（minimax/openai/anthropic/ollama）
  - run_v7_ingest 在 fake provider 下产出预期 WikiPage 列表
  - ConceptPage 适配后 round-trip 通过 `WikiPage.from_dict` / `to_dict`
  - source 页 stub 生成正确
- [ ] 测试用 temp root，与生产隔离

**Done 标志**：5 个测试通过；不修改 `ingest.py` 主路径

### Phase 2 — 干跑 + 影子模式

任务：
- [ ] 修复 `src/pipeline/shadow.py` 让 `run_shadow_ingest` 真正可调用（当前 dead code）
- [ ] `src/pipeline/ingest.py:742` 加 `_v7_mode` 分支（默认不启用）
- [ ] 影子模式接入：候选主路径 + V7 影子路径同时跑，写 `.index/shadow/<task_id>/`
- [ ] 对比报告生成（candidate vs v7 page count、slot 覆盖率、关键概念 diff）
- [ ] 烟测：把 KB `kb-20260918152026-4409dd89`（失败的 70 KB 任务）用 shadow mode 重跑，对比 V7 输出 vs candidate rejected 的 candidate.json
- [ ] 验证：知识库 lint/wiki-quality 不退化

**Done 标志**：shadow mode 跑成功；70 KB 任务 V7 输出能落盘到 .index/shadow

### Phase 3 — 灰度切换 + 监控

任务：
- [ ] 选 1 个非 novel-wiki-v2 项目（例如 video-notes-wiki），设 `RUFLO_PIPELINE_MODE=v7` 起服
- [ ] 监控 1 周：H1/H2/H4/H5 + wiki-quality strict + book build 是否通过
- [ ] 比较 v7 写入的页面前端格式 vs 旧候选页是否能被 lint 接受
- [ ] 检查 reconciliation（重复页面、heat 衰减等）是否正常
- [ ] 写评估报告（page count delta、slot 覆盖率、failure 率）

**Done 标志**：外部项目稳定运行 1 周；评估报告通过用户审阅

### Phase 4（可选）— 全量切换

任务：
- [ ] 与用户确认切换计划
- [ ] 候选路径标记 deprecated，保留 fallback 6 个月
- [ ] 文档：`docs/adr/0014-v7-ingest-default.md`（如果还没有）

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| V7 写出页面格式与 lint 不兼容 | H2/H5 全红 | Phase 2 shadow 对比；先单项目验证 |
| V7 LLM 调用次数 = 8+1/slot（v3 路径），比候选 1 次多 9× | 成本 9× | 用 `fill_slots` (v2 路径, 1 次) 而不是 `fill_slots_v2`；监控 cost metric |
| WikiWriter P4/`__other__` 闸门丢弃页 | 部分页面无人看见 | 走 review queue（已有）；UI 显示 |
| Stage 5 reviewer budget 无 fail-closed | LLM 超时静默通过 | F3 决议：保留 fail-closed 策略（已记录）；监控 reviewer 实际命中率 |
| Wiki 库格式混用 | lint 误报 | 保留旧页面，V7 写新页面用 `owner: v7` 区分；long-term 做 migration |
| V7 端到端入口是孤儿代码 | 维护风险 | bridge.py 实现时同步给所有 stage 模块加 docstring "called by src.pipeline.v7_extract.bridge" |

---

## 5. 不应做的事

1. **不要把 V7 强塞进 `ingest.py:run_ingest` 内部**——应该独立 bridge，让 `ingest.py` 只调度
2. **不要绕过 fail-closed**：V7 Stage 7 的 P4/has_evidence/needs_review 闸门不能关
3. **不要默认全量切换**：必须先 Phase 2 shadow 对比
4. **不要删除候选路径**：保留 6 个月作为回滚；评估后正式 deprecate
5. **不要假设 V7 比候选"更好"**：smoke-test 是单源，需要 Phase 2/3 才能确认多源 + 长源 + ASR 转录 + 网文风格都 OK

---

## 6. 关键代码位置（实施时直接打开）

| 文件 | 关键位置 |
| --- | --- |
| `src/pipeline/ingest.py` | line 742 `_candidate_mode` 处加 `_v7_mode` 分支 |
| `src/pipeline/ingest.py` | line 797-802 strict validate_evidence 是已知 bug，V7 不走这条路径自动绕开 |
| `src/pipeline/shadow.py` | 全文件 dead code，需要修才能 shadow mode |
| `src/pipeline/v7_extract/__init__.py` | `classify_doc` / `check_completeness` / `cluster_topics` / `fill_slots` 入口 |
| `src/pipeline/v7_extract/wiki_writer.py` | line 175 `commit_and_index` — V7 写入路径（已被 smoke-test 验证） |
| `src/pipeline/v7_extract/page_synthesizer.py` | line 325 `fill_slots_v2` — Stage 5B 主入口 |
| `src/pipeline/v7_extract/slot_filler.py` | line 45 `CONCEPT_SLOTS` — 8 槽位定义（与 wiki template 一致） |
| `scripts/extract_pilot.py` | line 89 `run_pilot` / line 190 `_extract_one` — 唯一端到端 orchestration 样板 |
| `src/v7_agl/agent.py` | line 53-57 — 已有 V7 LLMClient 适配范例（BaseURLLLMClient） |
| `src/llm/registry.py` | line 396 — minimax provider 派生（可复用） |
| `docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md` | line 42-50 — Wave 0 前置条件清单 |
| `.memory/feedback-v7-control-plane-real-provider-smoke-2026-09-15.md` | 唯一真实 Provider smoke 报告 |
| `.memory/feedback-v7-agl-design-tree-2026-09-18.md` | line 175 — "V7 端到端入口不存在"已记录 |
