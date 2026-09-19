# V7 Extract 替换候选管线（整改后 v2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Each task must complete its own test cycle and commit. Steps use checkbox syntax for tracking.

## 修订说明

v1 plan 完成后已走两轮 plan-audit：

- **第一轮**（`audit-r1.md`）找出 12 个 ①② 级问题（F1–F3 致命，H1–H9 重大）+ 10 个优化疏漏 + 6 个信息盲区
- **第二轮**（`audit-r2.md`）压力测试找出 11 个压力点（6 P0 + 3 P1 + 2 P2）+ 8 个边界条件

**v2 修订要点**（含在原 plan 基础上 +24 项改动）：
1. 新增 `src/pipeline/v7_extract/segmentation.py` 公开 deterministic splitter（替换 scripts/ 私有）
2. bridge 用 `classification.doc_type` plain string（v4 contract）+ 检查 `classification.failed` 提前 fail
3. bridge 用 `_result.canonical_text`（经 sanitize）+ `_result.prompt_blocks` 而非 raw content
4. bridge 调 V7 WikiWriter 写 concept 页；source stub 走 `commit_ingest` 写盘链路
5. bridge 返回 3-tuple `(pages, extras=[], meta)` + meta 含 `triage_result` / `readiness_audit` / `failed_topics` / `empty_extraction`
6. bridge 加 cost budget（`RUFLO_V7_MAX_USD` / `RUFLO_V7_MAX_CALLS`）+ per-stage timeout（`RUFLO_V7_STAGE_TIMEOUT_SEC`）
7. bridge 用 `_queue_lock.acquire(project_root, source_path)` 保护并发写
8. bridge 写 quarantine v7_markdown 摘要（保持向后兼容）
9. bridge exception 路径不写 reviews_queue（与 V7 设计一致）+ 写 `.index/quarantine/<task_id>/v7_failure.md`
10. bridge 加 source-page-existing check（merge/skip 现有 source 页）
11. bridge 计算 source_page sha256 + 传 `expected_page_hashes`
12. 调整 CircuitBreaker 阈值到 10（雪崩兜底）+ retries 默认 1
13. bridge 加 `len(content) > settings().max_source_chars * 4: raise`（OOM 兜底）
14. Task 5 + Task 6 合并为单一 commit（中间 commit 测试 import 失败问题）

**目标：** 让 `src.pipeline.v7_extract` 的 7 阶段管线成为 HTTP 摄取的唯一路径；删除候选（candidate）/旧 unified 路径及其代码、测试、env 变量、shadow mode；保留 AGL 训练链路。

**架构：** 新增 `src.pipeline.v7_extract.bridge.run_v7_ingest` 作为 ingest queue 的唯一入口，调用 Stage 1–7 + `WikiWriter.commit_and_index`；`src.pipeline.ingest.run_ingest` 第 576 行 `generate_ingest` 函数体替换为 `run_v7_ingest` 调用；下游 `commit_ingest` 不变（仍负责写盘 + index + lineage）。`src.pipeline.shadow.py` 整文件删除（dead code）。

**Tech Stack:** Python 3.11+, `asyncio`, 现有 `LLMClient` 抽象, 现有 `WikiWriter`, 现有 `commit_ingest` 写盘逻辑；不新增依赖。

## 启动前置（Wave 0 必须）

- [ ] **A1**. `git status` 干净
- [ ] **A2**. 用户确认 v1 plan 中 Task 5 + Task 6 合并到 Task 5a（避免中间 commit import 失败）
- [ ] **A3**. 用户确认成本预算默认（`RUFLO_V7_MAX_USD=0.5/source`、`RUFLO_V7_MAX_CALLS=20/source`、`RUFLO_V7_STAGE_TIMEOUT_SEC=120/stage`）
- [ ] **A4**. 用户确认默认 fill_slots 路径（v2 1 次 LLM vs v3 8+1 次 per-slot）—— v1 已选 v3，确认保留
- [ ] **A5**. 用户确认 source stub 走 commit_ingest（不通过 V7 WikiWriter），V7 WikiWriter 仅产 concept 页
- [ ] **A6**. 当前 `kb-20260918152026-4409dd89` 任务用新 bridge 重试 → 期望 succeeded

### 1.5 前置现状快照（Wave 0 主 agent 在 `git rev-parse HEAD` 后填写）

主 agent 应填写：

- 当前 `src/pipeline/ingest.py:576` `generate_ingest` 签名快照
- 当前 `src/pipeline/v7_extract/segmentation.py` 内容（应有 CanonicalItem / SegmentationResult，但无 deterministic splitter）
- 当前 `.index/kc/bundles/` 路径是否有数据
- 当前 production raw `knowledge/novel-wiki-v2/` 已有 wiki 页数
- 当前 server 状态（`http://127.0.0.1:19828`）

## Global Constraints

- 不动 `src.pipeline.v7_extract/*` Stage 1-7 内部代码（已通过 smoke + 30 测试验证）
- 不动 `commit_ingest`（V7 写入走现有写盘逻辑，保持兼容性）
- 不动 `src.pipeline.stages.*` 旧 stages（保留用于 CollectorStage，单独审）
- 不动 `src.pipeline.service.py:PipelineService.run_for_collector_start` 入口
- 不动 `src.queue.service.py`（queue 层无 RUFLO_PIPELINE_MODE 概念）
- 不动 `src.server.routes.ingest.py`（HTTP 层透明）
- 不动 `src.llm.*`（V7 bridge 适配 `LLMClient` 接口，不改 Provider API）
- 不动 `src.v7_agl.*`（AGL 训练保留 V7 USE_V3=false 走 v2 fallback）
- 不重写 Stage 1–7 内部
- 不删除 `tests/test_pipeline/test_v7_extract_*` (30 个文件)
- 不删除 `scripts/extract_pilot.py` 和 `scripts/extract_full.py`（dry-run CLI）

## 1. 文件职责地图

| 文件 | 重构后的唯一职责 |
|---|---|
| `src/pipeline/v7_extract/segmentation.py` *(扩展)* | 加 deterministic splitter 函数 (`extract_items_deterministic` / `wrap_items_as_segmentation_result` / `build_structural_summary`)；从 scripts/ 抽 |
| `src/pipeline/v7_extract/bridge.py` *(新)* | V7 端到端入口；接受现有 Provider + sanitized text，调 Stage 1–7，产出 WikiPage 列表 |
| `src/pipeline/v7_extract/llm_bridge.py` *(新)* | ProviderAdapter — 包装 `src.llm.*` Provider 适配 V7 `LLMClient.complete()` |
| `src/pipeline/v7_extract/page_adapter.py` *(新)* | ConceptPage ↔ WikiPage 适配；source stub WikiPage 生成 |
| `src/pipeline/ingest.py` | 修改 `generate_ingest` (line 576) 调用 `run_v7_ingest`；删除 candidate/chunked/unified 分支 |
| `src/pipeline/generator.py` | 删除 `unified_generate` 函数 (line 689-902)；保留 `generate_from_candidate` 以便被 AGL 等引用 |
| `src/pipeline/analyzer.py` | 删除 `_analyze` / `_analyze_chunked` / `_split_source_chunks` |
| `src/pipeline/shadow.py` | **删除整文件** |
| `src/config.py` | 删除 `pipeline_mode` + `shadow_mode` 字段 |
| `src/quality/quarantine.py` | 整文件保留但加 v7_failure_md 写入函数 |
| `src/pipeline/_queue_lock.py` | 暴露 `acquire(project_root, source_path)` 给 bridge |
| `tests/test_pipeline/test_pipeline.py` | 删除 `test_unified_generate_*` 4 个；保留 pipeline_terminal_status / event_bus_integration |
| `tests/test_pipeline/test_ingest_generate_commit_split.py` | 删除 candidate + unified test blocks |
| `tests/test_pipeline/test_chunked_analysis.py` | **删除整文件** |
| `tests/test_pipeline/test_ingest_kc_mainline.py` | 改写为 V7 bridge 失败-closed 测试 |
| `tests/test_pipeline/test_schema_purpose_injection.py` | 删除 legacy env set（line 44），改直接测 |
| `tests/test_e2e/test_ingest_happy_path.py` | 重写用 V7 bridge + FakeLLMClient |
| `tests/test_pipeline/test_v7_extract_bridge.py` *(新)* | bridge 端到端：FakeLLMClient + 4 种 Provider 适配 |
| `tests/test_pipeline/test_v7_extract_page_adapter.py` *(新)* | ConceptPage ↔ WikiPage 适配 round-trip |
| `tests/test_pipeline/test_v7_extract_segmentation.py` *(新)* | deterministic splitter 测试 |
| `tests/test_pipeline/test_v7_extract_quarantine.py` *(新)* | bridge 失败 → v7_failure.md 写入测试 |
| `docs/adr/0014-v7-ingest-default.md` *(新)* | 决策记录 |
| `docs/architecture/ingest-pipeline.md` *(新)* | V7 端到端架构文档 |

### V7 Bridge 接口契约

```
[src/pipeline/v7_extract/bridge.py]
@dataclass
class BridgeBudget:
    max_usd: float = 0.5
    max_calls: int = 20
    stage_timeout_sec: int = 120

@dataclass  
class BridgeResult:
    pages: list[WikiPage] = field(default_factory=list)
    extras: list[WikiPage] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # 含 triage_result, readiness_audit, failed_topics, empty_extraction

async def run_v7_ingest(
    *,
    paths: WikiPaths,
    source_path: Path,
    source_text: str,
    provider,  # src.llm.LLMProvider
    folder_context: str = "",
    task_id: str = "v7-bridge",
    schema_registry: SchemaRegistry | None = None,
    purpose_content: str = "",
    taxonomy_content: str = "",
    existing_wiki_index: str = "",
    use_fill_slots_v2: bool = True,
    budget: BridgeBudget = BridgeBudget(),
    preprocessed: PreprocessResult | None = None,  # 复用 ingest.py 传入的预处理结果
) -> BridgeResult:
```

### ProviderAdapter 接口契约

```
[src/pipeline/v7_extract/llm_bridge.py]
class ProviderAdapter(LLMClient):
    """将 src.llm.LLMProvider 适配为 V7 LLMClient 接口。
    
    不再持有自己的 base_url/api_key —— 直接 wrap 已构造的 Provider 实例。
    """
    def __init__(self, provider: LLMProvider):
        self._provider = provider
        self._cost_ledger: CostLedger | None = None  # 可选
        self._calls_count = 0
    
    async def complete(self, *, prompt_kind, user_prompt, system_prompt="", max_tokens=4096, temperature=0.0) -> str:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": user_prompt}]
        resp = await self._provider.chat(messages=messages, response_format=None)
        self._calls_count += 1
        return resp.content
```

### ConceptPage ↔ WikiPage 适配契约

```
[src/pipeline/v7_extract/page_adapter.py]
def adapt_concept_page(page: ConceptPage, *, schema_registry=None) -> WikiPage:
    """ConceptPage → WikiPage（8 槽位 → 8 个 ## section）"""
    # body: "\n\n".join(f"## {ZH_HEADING}\n{slot_body}" for name in slot_body in page.slots.items())
    # frontmatter: id, title, type="concept", sources, relations, _ko_extra.slot_evidence
    # tags: 从 schema_registry 派生（如 "category/concept"）；不传则空
    # processing_depth: "concept"
    # heat: 50 (default)
    # 不写 v7 元数据到 frontmatter（V7 WikiWriter 自己注入 owner: v7）

def build_source_stub_page(
    source_path: Path,
    source_text: str,
    task_id: str,
    *,
    paths: WikiPaths,
    concept_page_ids: list[str] = None,
) -> WikiPage:
    """生成 source 摘要 stub 页。
    
    必须由 commit_ingest 通过 page_path_for 写到 wiki/sources/，
    不能交给 V7 WikiWriter（V7 WikiWriter 不分 type，全部写 wiki/concepts/）。
    
    body 含: 来源元数据 + 转录质量(stub="人工整理") + 摘要(stub="(无摘要)") + 
            关键观点(links → concept_page_ids 列表) + 可信度声明
    relations: references → 所有 concept_page_ids
    """
```

### segmentation.py 扩展

```
[src/pipeline/v7_extract/segmentation.py] 在原文件末尾追加：
def extract_items_deterministic(content: str, relative: str) -> list[CanonicalItem]:
    """从 scripts/extract_pilot.py:792 抽出。
    基于 byline/heading/numbered-list/single-item fallback 切分。
    不调 LLM。
    """

def wrap_items_as_segmentation_result(items, *, content, source_md5, relative) -> SegmentationResult:
    """从 scripts/extract_pilot.py:661 抽出。"""

def build_structural_summary(segmentation_result, *, content) -> dict:
    """从 scripts/extract_pilot.py:629 抽出。"""
```

`scripts/extract_pilot.py:792` 等改为 import 这些函数。

## 2. 任务列表（每 Task 一 commit + 单独测试通过）

### Task 1: 扩展 segmentation.py + 抽出 deterministic splitter

**Files:**
- `src/pipeline/v7_extract/segmentation.py` (扩展)
- `scripts/extract_pilot.py` (改为 import)
- `tests/test_pipeline/test_v7_extract_segmentation.py` (新)

**Tests:**
- `test_extract_items_byline` — 多个 `作者 XXX` 格式能切出多个 item
- `test_extract_items_heading` — `## 标题` 切出多个 item
- `test_extract_items_numbered` — `1. xxx` 切出多个 item
- `test_extract_items_single_fallback` — 单短文本 fallback
- `test_extract_items_empty_content` — 空内容返回 []
- `test_wrap_items_creates_canonical_items` — SegmentationResult 含正确 start_byte/end_byte
- `test_build_structural_summary_includes_header_byline_qa_counts`

**Implementation:**
- 把 `scripts/extract_pilot.py:792-841` 函数复制到 `v7_extract/segmentation.py`
- 把 `scripts/extract_pilot.py:629-660` (`_build_structural_summary`) 抽出
- 把 `scripts/extract_pilot.py:661-790` (`_wrap_items_as_segmentation_result`) 抽出
- 把 `scripts/extract_pilot.py:842` 之后 (byline RE) 抽出到 constants
- scripts/extract_pilot.py 改为 `from src.pipeline.v7_extract.segmentation import (...)`
- **回归 scripts/extract_pilot.py 自己**：`python scripts/extract_pilot.py --help` 不报错；单文件 dry-run 仍能跑（用现有 `--dry-run`）

**Acceptance:**
- 新增 7 个测试全绿
- 现有 `scripts/extract_pilot.py` 相关测试 (`tests/test_pipeline/test_v7_extract_gold_corpus.py`) 通过
- scripts/extract_pilot.py 改为 import 后跑 `--dry-run --root /tmp/foo --count 1` 不报错（虽然 dry-run 行为不变）

**Commit:** `refactor(v7-segmentation): extract deterministic splitter from scripts/extract_pilot.py`

---

### Task 2: 实现 ProviderAdapter + 单测

**Files:**
- `src/pipeline/v7_extract/llm_bridge.py` (新)
- `tests/test_pipeline/test_v7_extract_llm_bridge.py` (新)

**Tests:**
- `test_adapter_forwards_chat_to_provider` — verify ProviderAdapter.complete() 调用底层 provider.chat()
- `test_adapter_prepends_system_message` — system_prompt 正确放在 messages[0]
- `test_adapter_omits_system_when_empty` — 空 system_prompt 不污染 messages
- `test_adapter_forwards_response_format` — response_format={"type": "json_object"} 透传
- `test_adapter_returns_resp_content_str` — 返回 str，不是 LLMResponse
- `test_adapter_increments_calls_count` — 每次 complete() 自增计数
- `test_adapter_health_check` — health_check 透传
- `test_adapter_for_anthropic` — 走 AnthropicProvider（验证 system prompt 拼接正确）
- `test_adapter_for_ollama` — 走 OllamaProvider
- `test_adapter_for_minimax_openai_compat` — 走 OpenAIProvider with minimax config

**Implementation:**
- 仅 ~80 行
- `complete()` 调 `await provider.chat(messages=..., response_format=None)`
- 返回 `resp.content`
- `health_check()` 调 `provider.health_check()`
- `calls_count` 内部 counter（bridge 用它做 budget check）

**Acceptance:**
- 10 个测试通过
- 不动现有 Provider

**Commit:** `feat(v7-bridge): add ProviderAdapter for src.llm.* → v7 LLMClient`

---

### Task 3: 实现 ConceptPage ↔ WikiPage 适配 + 单测

**Files:**
- `src/pipeline/v7_extract/page_adapter.py` (新)
- `tests/test_pipeline/test_v7_extract_page_adapter.py` (新)

**Tests:**
- `test_adapt_concept_page_basic` — 8 槽位全填 → WikiPage.body 含 8 个 `## {zh_heading}\n{body}` 段
- `test_adapt_concept_page_partial_5_slots` — 仅 5 槽位填 → body 只含 5 段
- `test_adapt_concept_page_preserves_id_title_type`
- `test_adapt_concept_page_sources_field_passthrough`
- `test_adapt_concept_page_relations_field` — slot_evidence → _ko_extra
- `test_adapt_concept_page_round_trip_dict` — WikiPage.to_dict/from_dict 保留 slot evidence
- `test_build_source_stub_minimal` — source 页含 stub 全部 section
- `test_build_source_stub_with_relations` — source 页 relations 指向 concept 页
- `test_build_source_stub_no_concept_pages` — 空 concept list 时关键观点为空
- `test_adapt_concept_page_with_other_topic_id_sentinel` — `topic_id == "__other__"` 时抛 InvalidInputError

**Implementation:**
- `adapt_concept_page(page, *, schema_registry=None)` ~40 行
- `build_source_stub_page(source_path, source_text, task_id, *, paths, concept_page_ids=None)` ~50 行
- 槽位顺序：`definition, characteristics, context, anti_patterns, evidence, examples, related_concepts, references`（按 `_SLOT_HEADINGS`）
- 中文标题映射硬编码（与现有 wiki template 一致）
- `OTHER_TOPIC_ID` 防御抛 InvalidInputError

**Acceptance:**
- 9 个测试通过
- 适配产物 WikiPage 能通过现有 `WikiPage.from_dict` / `to_dict` round-trip

**Commit:** `feat(v7-bridge): add ConceptPage ↔ WikiPage adapter`

---

### Task 4: 实现 run_v7_ingest bridge + 单测

**Files:**
- `src/pipeline/v7_extract/bridge.py` (新)
- `tests/test_pipeline/test_v7_extract_bridge.py` (新)

**Tests:**
- `test_bridge_runs_full_pipeline` — FakeLLMClient 跑 stage 1–7；断言产出 WikiPage 列表
- `test_bridge_handles_long_source_22k` — 22k 源 > 16k max_source_chars；不崩
- `test_bridge_propagates_provider_errors` — LLM 抛错时 bridge 返回 failure meta 不写盘
- `test_bridge_with_use_fill_slots_v2_false` — 显式切回 v2 path（默认 True）
- `test_bridge_returns_bridge_result_with_required_keys` — 返回值 schema
- `test_bridge_handles_classification_failed` — Stage 1 failed=True → return FAILED meta, pages=[]
- `test_bridge_handles_completeness_incomplete` — Stage 3 INCOMPLETE → return INCOMPLETE meta
- `test_bridge_skips_pages_with_no_evidence` — V7 P4 闸门生效
- `test_bridge_skips_pages_with_needs_review` — needs_review 闸门生效
- `test_bridge_returns_empty_extraction_when_complete_block` — 全部被 block 时 extras=None, pages=[]
- `test_bridge_calls_stage2_deterministic_splitter` — 验证 Stage 2 走 `extract_items_deterministic` 而非 LLM
- `test_bridge_budget_exceeded_aborts` — `RUFLO_V7_MAX_USD=0.001` 触发 budget exceeded
- `test_bridge_stage_timeout_aborts` — `RUFLO_V7_STAGE_TIMEOUT_SEC=1` 触发 timeout
- `test_bridge_writes_quarantine_v7_failure_on_exception` — 异常路径写 `.index/quarantine/<task_id>/v7_failure.md`

**Implementation:**
- `run_v7_ingest()` ~200 行（含 budget + timeout + exception handling）
- 调用链：
  ```
  preprocessed = preprocessed or preprocess_source(source_text, source_id=source_key)
  sanitized_text = preprocessed.prompt_text or preprocessed.canonical_text
  
  llm_adapter = ProviderAdapter(provider)
  budget = BridgeBudget.from_env()
  
  with _queue_lock.acquire(paths.root, str(source_path)):
      result = BridgeResult()
      
      # Stage 1
      classification = await classify_doc(sanitized_text, ..., llm=llm_adapter, project_root=paths.root)
      if classification.failed:
          result.meta["failure_stage"] = "stage1"
          result.meta["failure_reason"] = classification.error
          _write_v7_failure_markdown(paths, task_id, "stage1_failed", ...)
          return result
      
      # Stage 2 deterministic
      items = extract_items_deterministic(sanitized_text, str(source_path))
      segmentation_result = wrap_items_as_segmentation_result(items, content=sanitized_text, ...)
      structural_summary = build_structural_summary(segmentation_result, content=sanitized_text)
      
      # Stage 3
      completeness = await check_completeness(sanitized_text, doc_type_hint=classification.doc_type,
                                              llm=llm_adapter, project_root=paths.root,
                                              structural_summary=structural_summary)
      if completeness is None or completeness.status is CompletenessStatus.TECHNICAL_FAILURE:
          ... return FAILED
      if completeness.status is CompletenessStatus.INCOMPLETE:
          result.meta["failure_stage"] = "stage3_incomplete"
          return result
      
      # Stage 4
      cluster = await cluster_topics(items, llm=llm_adapter, project_root=paths.root,
                                    segmentation_result=segmentation_result)
      if cluster.status in {ClusterStatus.EMPTY, ClusterStatus.UNCERTAIN}:
          ... return BLOCKED
      
      # Stage 5 per topic
      concept_pages: list[ConceptPage] = []
      failed_topics: list[str] = []
      for topic in cluster.topics:
          if topic.id == OTHER_TOPIC_ID:
              continue
          try:
              if use_fill_slots_v2:
                  result_topic = await fill_slots_v2(
                      topic, spans_per_slot=..., topic_items=items, source_bytes=sanitized_text.encode(),
                      llm=llm_adapter, project_root=paths.root,
                  )
                  if result_topic.status == FillStatus.FILLED:
                      concept_pages.append(result_topic.page)
                  else:
                      failed_topics.append(topic.id)
              else:
                  page = await fill_slots(topic, source_text=topic_text, llm=llm_adapter,
                                          item_texts=item_map, project_root=paths.root)
                  if page is not None:
                      concept_pages.append(page)
                  else:
                      failed_topics.append(topic.id)
          except Exception as e:
              logger.warning("[v7-bridge] fill_slots failed for topic %s: %s", topic.id, e)
              failed_topics.append(topic.id)
      
      # Stage 6
      relations = extract_relations(concept_pages, llm=llm_adapter)
      
      # Stage 7 — write concept pages via V7 WikiWriter
      writer = WikiWriter(root=paths.root)
      report = writer.commit_and_index(concept_pages, relations)
      
      # Adapt V7 pages → WikiPage
      result.pages = [adapt_concept_page(p) for p in report.written]
      result.meta["written"] = list(report.written)
      result.meta["blocked"] = list(report.blocked)
      result.meta["failed"] = dict(report.failed)
      result.meta["failed_topics"] = failed_topics
      result.meta["concept_page_ids"] = [p.id for p in result.pages]
      
      if not result.pages and not failed_topics:
          result.meta["empty_extraction"] = True
          _write_v7_failure_markdown(paths, task_id, "empty_extraction", ...)
      
      # Source stub — 走 commit_ingest 写盘路径（不进 V7 WikiWriter）
      result.pages.append(build_source_stub_page(source_path, source_text, task_id,
                                                paths=paths,
                                                concept_page_ids=result.meta["concept_page_ids"]))
      return result
  ```

**Acceptance:**
- 14 个测试通过
- bridge 不直接写盘（写盘走 commit_ingest）
- bridge 失败时不写 partial state
- budget + timeout 触发的失败都写 v7_failure.md

**Commit:** `feat(v7-bridge): add run_v7_ingest end-to-end entry`

---

### Task 5: 改造 generate_ingest 调用 V7 bridge

**Files:**
- `src/pipeline/ingest.py` (修改 generate_ingest body, line 576+)
- `src/pipeline/ingest.py` (删除 line 742-883 candidate 分支)
- `src/pipeline/ingest.py` (删除 line 884-955 chunked + unified 分支)
- `src/pipeline/ingest.py` (删除 line 1457-1505 _merge_candidate_chunks)
- `src/pipeline/ingest.py` (删除 line 1543-1580 _merge_analysis_results, _split_source_chunks)
- `src/pipeline/ingest.py` (删除 _analyze, _analyze_chunked, _analyze_legacy imports)

**Tests:** 现有测试改写（见 Task 5a）。

**Implementation:**
- `generate_ingest` 函数体替换：
  ```python
  async def generate_ingest(paths, source_path, source_text, provider, folder_context="", task_id="test", schema_registry=None):
      from .v7_extract.bridge import run_v7_ingest
      from .text_preprocessing import preprocess_source
      
      if schema_registry is None:
          schema_registry = SchemaRegistry.from_project(paths.root)
      
      _schema_text = _read_schema_text(paths)
      _purpose_text = _read_purpose_text(paths)
      _taxonomy_text = _read_taxonomy_text(paths)
      
      # Lineage
      from ..lineage import LineageStore
      LineageStore.open(paths.root).ensure_source(source_path, source_text=source_text)
      
      # Preprocess (sanitize)
      preprocessed = preprocess_source(source_text, source_id=str(source_path),
                                        source_bytes_sha256=hashlib.sha256(source_text.encode()).hexdigest())
      
      # Call V7 bridge
      bridge_result = await run_v7_ingest(
          paths=paths, source_path=Path(str(source_path)), source_text=source_text,
          provider=provider, folder_context=folder_context, task_id=task_id,
          schema_registry=schema_registry, purpose_content=_purpose_text,
          taxonomy_content=_taxonomy_text,
          preprocessed=preprocessed,
      )
      
      # Compute expected_page_hashes for source page (idempotency)
      expected_page_hashes = {}
      for page in bridge_result.pages:
          if page.type == PageType.SOURCE:
              # Compute hash of rendered page
              from src.wiki.storage.page_writer import _validate_slug
              from ..wiki.core.types import WikiPage
              rendered = page.to_dict() if hasattr(page, 'to_dict') else page
              expected_page_hashes[page.id] = hashlib.sha256(
                  yaml.safe_dump(rendered, allow_unicode=True, sort_keys=False).encode()
              ).hexdigest()
      
      meta = {
          "written": bridge_result.meta.get("written", []),
          "blocked": bridge_result.meta.get("blocked", []),
          "failed": bridge_result.meta.get("failed", {}),
          "failed_topics": bridge_result.meta.get("failed_topics", []),
          "empty_extraction": bridge_result.meta.get("empty_extraction", False),
          "concept_page_ids": bridge_result.meta.get("concept_page_ids", []),
          "triage": bridge_result.meta.get("triage_result"),
          "missing_slugs": [],  # reconcile 阶段填
          "readiness_audit": bridge_result.meta.get("readiness_audit"),
      }
      return bridge_result.pages, [], meta
  ```
- 删除 line 742-883 整个 candidate 分支
- 删除 line 884-955 整个 chunked + unified 分支
- 删除 `_candidate_mode` 变量
- 删除 import: `from .analyzer import analyze`, `from .generator import generate_from_candidate`, `from src.kc.mainline import CandidatePromoter, CandidateReviewer`, `from .text_preprocessing import chunk_prompt_blocks`, `from .generator import unified_generate`, `from src.kc.compiler.evidence import validate_evidence`, `from .generator import _clean_placeholder_text`
- 删除 `_kc_review`, `_kc_promotion`, `_pilot_audit`, `_audit_evidence` 变量
- 删除 `from ..quality.quarantine import QuarantineStore` 的相关 call（保留 import 自身）
- line 1300+ reconcile 部分保留（bridge 写完后仍需要）

**Acceptance:**
- `tests/test_pipeline/test_ingest_kc_mainline.py` 改写后通过
- `tests/test_e2e/test_ingest_happy_path.py` 改写后通过
- 现有 `commit_ingest` 调用链不变

**Commit:** `refactor(ingest): replace candidate/legacy paths with V7 bridge`

---

### Task 5a: 删除 generator/analyzer/shadow/config 旧路径 + 更新测试（合并 commit）

**Files:**
- `src/pipeline/generator.py` (删除 line 689-902 `unified_generate`)
- `src/pipeline/analyzer.py` (删除 `_analyze`, `_analyze_chunked`, `_split_source_chunks`)
- `src/pipeline/shadow.py` (删除整文件)
- `src/config.py` (删除 `pipeline_mode` + `shadow_mode` 字段)
- `tests/test_pipeline/test_pipeline.py` (删除 `test_unified_generate_*` 4 个)
- `tests/test_pipeline/test_ingest_generate_commit_split.py` (删除 candidate + unified test blocks)
- `tests/test_pipeline/test_chunked_analysis.py` (删除整文件)
- `tests/test_pipeline/test_ingest_kc_mainline.py` (改写为 V7 bridge 失败-closed 测试)
- `tests/test_pipeline/test_schema_purpose_injection.py` (删除 legacy env set)
- `tests/test_e2e/test_ingest_happy_path.py` (重写用 V7 bridge + FakeLLMClient)

**Tests:**
- Task 5a 测试 = 上述测试改写后的全绿
- `python -c "import src.pipeline.shadow"` 应 ImportError
- `grep -r "RUFLO_PIPELINE_MODE\|RUFLO_SHADOW_MODE\|unified_generate\|_analyze_chunked\|_merge_candidate_chunks\|_merge_analysis_results" src/ tests/` 应 0 命中（除 V7 USE_V3）

**Implementation:**
- 详见 Task 5 + Task 6 描述
- 单 commit 完成所有删除

**Acceptance:**
- 全部测试通过
- 删除后的代码无 dead imports

**Commit:** `chore(cleanup): remove deprecated candidate/legacy pipeline code + update tests`

---

### Task 6: 端到端 smoke + 灰度切换

**Files:** 不新增

**Tests:**
- `PYTHONPATH=. pytest --import-mode=importlib tests/test_pipeline/test_v7_extract_bridge.py tests/test_pipeline/test_v7_extract_page_adapter.py tests/test_pipeline/test_v7_extract_llm_bridge.py tests/test_pipeline/test_v7_extract_segmentation.py -v`
- `PYTHONPATH=. pytest --import-mode=importlib tests/` 全套（确认无回归）
- 手动 smoke：
  1. 启动 server: `python -m src.cli serve --port 19828`
  2. curl ingest 同 70KB 源: `curl -X POST http://127.0.0.1:19828/api/v1/projects/9be6839c-3a38-43e2-88cf-0fdb37fe3e1c/ingest -H "Content-Type: application/json; charset=utf-8" --data-binary @.tmp-ingest-payload.json`
  3. 验证 status: succeeded（V7 不受 `validate_evidence` strict 检查限制）
  4. 检查 `.index/quarantine/` 是否未被写入（V7 失败用 reviews_queue + v7_failure.md）
  5. 检查 `wiki/concepts/` 是否含 1+ concept 页 + 1 source stub
  6. 检查 `wiki/_stubs/` 是否被 V7 写入（应该不会）
  7. 检查 H1/H2/H4/H5 + wiki-quality 是否仍 HEALTHY
  8. 检查 cost ledger：1 source ≤ 0.5 USD

**Acceptance:**
- `kb-20260918152026-4409dd89` 重跑 → succeeded
- 现有 wiki pages（来自上一轮 failed task）保留
- cost 在 budget 内
- quarantine 不被 V7 失败路径污染

**Commit:** `chore(verify): V7 ingest e2e smoke against 70KB audio source`

---

### Task 7: 文档 + ADR

**Files:**
- `docs/adr/0014-v7-ingest-default.md` (新)
- `docs/architecture/ingest-pipeline.md` (新)
- `README.md` (更新)
- `AGENTS.md` (更新)
- `CLAUDE.md` (更新)
- `.memory/feedback-v7-ingest-replace-candidate-2026-09-18.md` (新)

**Content:**
- **ADR-0014**: 决策 `RUFLO_PIPELINE_MODE` 不再存在；V7 是唯一摄取路径；删除 shadow mode；引用 ADR-0007 (candidate ownership) + plan 2026-09-15 control plane
- **架构文档**: V7 7 阶段 + bridge + commit_ingest 写盘 + lineage state
- **README**: 更新 HTTP 流程图；删除对 candidate/legacy 的引用
- **AGENTS.md/CLAUDE.md**: 同步 ingest 流程描述
- **Memory**: 记录实施过程 + 实际测试结果 + 删了什么代码

**Acceptance:**
- ADR 通过用户 review
- 4 个文档 + memory 全部更新
- 用户签署 ADR-0014

**Commit:** `docs(adr-0014): record V7 ingest as default pipeline`

---

## 3. 验收标准

- [ ] 所有 Task 1-7 完成
- [ ] `grep -r "RUFLO_PIPELINE_MODE\|RUFLO_SHADOW_MODE\|unified_generate" src/` = 0 命中（除 V7 USE_V3）
- [ ] `python -c "import src.pipeline.shadow"` → ImportError
- [ ] `python -m pytest --import-mode=importlib tests/` 全绿（或已知失败明确列出 + 用户确认）
- [ ] `python -m src.cli serve --port 19829` 启动成功，`/health` 返回 ok
- [ ] `kb-20260918152026-4409dd89` 重摄取 → succeeded
- [ ] `wiki-quality --project knowledge/novel-wiki-v2` HEALTHY
- [ ] ADR-0014 通过用户 review
- [ ] cost 单源 < 0.5 USD
- [ ] V7 失败不污染 `.index/quarantine/` (走 v7_failure.md + reviews_queue)

## 4. 回滚方案

每个 Task 独立 commit。回滚顺序：

1. Task 6 / Task 7 (撤销 e2e smoke 和文档)
2. Task 5 / Task 5a (撤销代码删除，回到 V7 + 旧代码并存状态)
3. Task 4 / Task 3 / Task 2 (撤销 bridge 实现)
4. Task 1 (撤销 segmentation 抽出)

最坏情况：保留 V7 bridge + Task 1 抽出，但 ingest.py 仍走旧候选路径。**V7 bridge 自身无破坏性，可独立保留供未来切换**。

## 5. 不应做的事

1. 不重写 Stage 1–7 内部
2. 不修改 WikiWriter 的 4-gate 闸门
3. 不修改 commit_ingest 的写盘逻辑
4. 不删除 V7 bridge / adapter / page_adapter / segmentation 抽出（即便主路径回滚，组件仍可重用）
5. 不删除 .memory/ 与 docs/superpowers/plans/ 中的旧条目（历史可追溯）
6. 不删除 src/v7_agl/*（AGL 训练链路）
7. 不删除 tests/test_pipeline/test_v7_extract_* (30 个文件)
8. 不删除 scripts/extract_pilot.py 和 scripts/extract_full.py
9. 不把 V7 WikiWriter 用于 source stub（必须走 commit_ingest）
10. 不增加新依赖（asyncio / dataclasses / yaml 已有）

## 6. v1 → v2 修订对照

| v1 问题 | v1 内容 | v2 修订 |
| --- | --- | --- |
| F1 fill_slots 返回 None 时崩溃 | `result.fill_status == FILLED` | v2 用 `if page is None: continue`（v2 path）+ `FillStatus.FILLED`（v3 path） |
| F2 跳过 Stage 2 deterministic | 直接调 `cluster_topics(content)` | Task 1 抽出 deterministic splitter → Task 4 bridge 调 `extract_items_deterministic` |
| F3 source stub 路径错 | V7 WikiWriter 写 | Task 3 `build_source_stub_page` + Task 5 `generate_ingest` 显式 append 到 pages 列表 → commit_ingest 路由到 `wiki/sources/` |
| H1 meta schema 不一致 | 没写 | Task 5 generate_ingest meta 填 `triage` / `readiness_audit` |
| H2 cost 无 budget | 无 | Task 4 `BridgeBudget` class + env vars |
| H3 中间 commit import 失败 | Task 5/6 分离 | Task 5 + Task 5a 合并单一 commit |
| H4 quarantine 路径消失 | 未提 | Task 4 写 `v7_failure.md` 摘要保持向后兼容 |
| H5 reconcile 数据源变形 | 未提 | Task 3 `build_source_stub_page` 不写 wikilinks |
| H6 readiness_audit 缺失 | 未提 | Task 4 bridge 构造 readiness_audit dict |
| H7 V7 WikiWriter source slug | 未提 | Task 3 source stub 用 ingest.py 命名 |
| H8 scripts/ 私有函数依赖 | 未提 | Task 1 抽出到 v7_extract.segmentation |
| H9 analyzer.py dead code | 未提 | Task 5a 删 analyzer 整文件 |
| O1-O10 | 优化疏漏 | 各项具体落实在对应 Task |
| ST1-ST11 | 压力点 | 各项具体落实在对应 Task |
