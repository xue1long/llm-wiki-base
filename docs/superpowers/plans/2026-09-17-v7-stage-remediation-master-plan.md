# Plan: V7 Stage 1–7 + Reconciliation 全链路整改 Master Plan

status: approved
branch: feature/2026-09-17-v7-stage-remediation
approved: 2026-09-17

---

## 0. 阅读须知

本 plan 是 V7 ingestion pipeline 八阶段整改的统一 master plan。每个 stage 的整改经过三轮对话迭代（用户设计 → 我评估 → 决策对齐），最终形成 8 个 sub-stage 的可执行任务 + 完整依赖图 + 阶段门控。

**本 plan 在进入编码阶段前必须通过 `plan-audit` 两轮审查：**
- **Round 1**：全面漏洞审计（跨 stage 一致性、blast radius、约束遗漏、错误模式）
- **Round 2**：压力测试推演（极端 source、长文、provider 故障、并发、迁移）

**用户当前阶段：架构设计与方案审查阶段（mattpocock 系，ponytail 关闭）。**

按 `dev-relay` 规则，**未通过两轮审查前严禁进入编码阶段**。

---

## 1. Goal

### 1.1 用户可见成果

把当前 V7 ingestion pipeline 从"七阶段 + 孤儿 Stage 6 + 孤儿 Reconciliation"升级为"九层清晰分离的子系统 + Knowledge Reconciliation Plane"，形成可长期积累的知识库。

具体：
1. Stage 1-7 每一阶段的 LLM 调用有**硬边界**（不能创造 page_id / canonical_id / topic_id）
2. Stage 1-7 每一阶段都有**显式 status contract**（五态外 stage-local enum，不污染全局状态机）
3. Stage 1-7 每一阶段都有**fingerprint**（接入 source checkpoint 双键，pipeline 升级可触发重判）
4. Stage 1-7 每一阶段都有**bounded evidence**（不裸读整篇，HEAD/TAIL/window/descriptor/pack）
5. Stage 5 升级为**claim-level evidence**（先 evidence 后 claim，先 claim 后 page）
6. Stage 6 升级为**独立异步 relation enrichment job**（不破坏 page written，full lifecycle）
7. Stage 7 升级为**crash-proof commit protocol**（CommitManifest + forward recovery + idempotent）
8. **新增 Knowledge Reconciliation Plane**（canonical_id 与 name 解耦 + reversible membership + decision log）

### 1.2 显式 non-goals

- 不重写 V7 主架构（保留 Collector → Analyzer → Generator 七阶段主链路）
- 不引入新的存储后端（仍用 Wiki Markdown + JSONL sidecars）
- 不改变 `ExtractionStatus` 五态（每 stage 用 stage-local enum，五态映射在 caller 端做）
- 不破坏现有 `Stage 1-7` 主链路（仍可同步运行，remediation 在主链路之后）
- 不在第一批实现 claim reconciliation（Phase 2 留后续 plan）
- 不在第一批实现跨文档 same_as 传递闭包（Phase 3 留后续 plan）
- 不引入新 CLI 框架（沿用 `python -m src.cli`）

### 1.3 整体架构总览

整改后 V7 形成**九层清晰分离的子系统**：

```text
Layer 0 — Raw Source
       ↓
Layer 1 — Evidence (Item / Span / byte offset)
       ↓
Layer 2 — Segmentation (canonical items + byte spans + invariant validation)
       ↓
Layer 3 — Completeness (proven_incomplete / uncertain / failed)
       ↓
Layer 4 — Topic Clustering (canonical topic candidates + quality gates)
       ↓
Layer 5 — Slot Filling (evidence-backed claims + semantic reviewer)
       ↓
Layer 6 — Wiki Writer (durable commit + CommitManifest + forward recovery)
       ↓
Layer 7 — Source-local Pages (committed, immutable-ish, with ownership)
       ↓
─────────────────────────────────────
Knowledge Reconciliation Plane
─────────────────────────────────────
Layer 8 — Canonical Concepts (Phase 1: identity + alias + reversible membership)
       ↓ (Phase 2, 后续)
Layer 9 — Canonical Claims + Relations
```

每一层都是同一个控制面原则：**LLM 管语义，脚本管机制，下一层不破坏上一层的事实。**

---

## 2. 跨 Stage 依赖图

```
                    ┌──────────────────┐
                    │  Stage 1 整改     │
                    │  doc_classifier  │
                    │  + traits/failed │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 2 整改     │
                    │  SegmentationResult│
                    │  + byte spans    │
                    │  + invariants    │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 3 整改     │
                    │  CompletenessResult│
                    │  + Stage 2 消费   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 4 整改     │
                    │  ClusterResult   │
                    │  + topic_id hash │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 5 整改     │ ←──── 依赖 Stage 2 byte spans
                    │  Claim/Evidence  │
                    │  + reviewer      │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 7 整改     │
                    │  CommitManifest  │
                    │  + recovery      │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Stage 6R 整改    │ ←──── 依赖 Stage 7 page_id 稳定
                    │  Async enrichment│
                    │  + lifecycle     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Reconciliation  │ ←──── 依赖 Stage 5 claim
                    │  Phase 1         │       ← 依赖 Stage 7 ownership
                    │  identity only   │
                    └──────────────────┘
```

### 2.1 阶段门控（Phase Gates）

每个 sub-stage 必须满足下列硬约束才能进入下一个 stage：

| 当前 Stage 完成 | 下一个 Stage 可启动的前提 |
|---|---|
| Stage 1 完成 | 后续 stage 必须使用 `Classification.failed/uncertain/traits/fingerprint` 字段 |
| Stage 2 完成 | 后续 stage 必须使用 `CanonicalItem.start_byte/end_byte`（UTF-8 byte offset against original source bytes） |
| Stage 3 完成 | Stage 3 内部不再有 `(False, str)` 失败返回（必须 `None` 或 `CompletenessResult`）|
| Stage 4 完成 | `Topic.id` 必须是脚本生成的 hash 字符串（不依赖 LLM title）|
| Stage 5 完成 | `FillResult` 必须有 `metrics.claim_support_ratio`，reviewer 已接入 high-risk claims |
| Stage 6R 完成 | `RelationStore` 已能独立 checkpoint，page written 不被破坏 |
| Stage 7 完成 | Wiki files 有 frontmatter `owner: v7 / pipeline_fingerprint / revision_hash` |
| Reconciliation 完成 | `canonical_id` 与 page_id 完全解耦，reversible membership 可用 |

### 2.2 跨阶段共享变量

| 共享变量 | 提供者 | 消费者 |
|---|---|---|
| `classifier_fingerprint` | Stage 1 | Stage 7 pipeline_fingerprint |
| `segmenter_fingerprint` | Stage 2 | Stage 7 pipeline_fingerprint |
| `checker_fingerprint` | Stage 3 | Stage 7 pipeline_fingerprint |
| `clusterer_fingerprint` | Stage 4 | Stage 7 pipeline_fingerprint |
| `generator_fingerprint` | Stage 5 | Stage 7 pipeline_fingerprint |
| `extractor_fingerprint` | Stage 6R | (n/a, 独立) |
| `CanonicalItem.start_byte/end_byte` | Stage 2 | Stage 3 / Stage 5 / Stage 7 |
| `CanonicalSpan` | Stage 5 | Stage 6R evidence |
| `Topic.id` (script-hash) | Stage 4 | Stage 7 |
| `Page frontmatter.owner` | Stage 7 | Reconciliation |

---

## 3. 统一控制面原则（所有 stage 共同遵守）

### 3.1 LLM 与 Script 的边界

**LLM 拥有**：
- 语义判断（trails / boundary type / claim text / decision）
- 风险评估（uncertain / high-risk / conflicting）
- 选择（allowed predicate / allowed decision）

**Script 拥有**：
- Identity（classification.primary_type / item_id / span_id / topic_id / claim_id / relation_id / canonical_id / commit_id）
- Coordinates（byte offset / span index / candidate index）
- Invariant validation（10-12 条 mechanical invariants）
- Status mapping（stage-local enum → ExtractionStatus 五态）
- Lifecycle（pending/active/stale/tombstone）
- Checkpoint & recovery

### 3.2 bounded evidence（不允许裸读整篇）

每个 stage 喂给 LLM 的输入都必须有硬预算：

| Stage | 输入形式 | 硬预算 |
|---|---|---|
| Stage 1 | evidence pack | 4000 bytes |
| Stage 2 | candidate windows | 每个 1500 chars |
| Stage 3 | HEAD + TAIL + structural signals | 2000+2000 bytes |
| Stage 4 | TopicDescriptor per item | 600 bytes |
| Stage 5 | canonical spans | 1500+200 bytes |
| Stage 6R | candidate pairs | 30 pairs per page |
| Reconciliation | candidate retrieval top-N | 20 candidates per page |

### 3.3 Fingerprint 双键

每个 stage 都必须暴露 fingerprint 字段。source checkpoint 从单 md5 升级为 md5 + pipeline_fingerprint 双键：

```
source_skip = md5_match AND pipeline_fingerprint_match AND status in {WRITTEN with all pages}
```

### 3.4 技术失败分离

每个 stage 都有三类失败：

1. **技术失败**（LLM timeout / parse error / IO failure）→ `failed` 状态 → retry
2. **证据不足**（无 candidate / 无证据 / 不在 ontology）→ `blocked` 状态 → review
3. **语义冲突**（多个 evidence 互相矛盾）→ `uncertain/conflicting` 状态 → review

**永远不允许**把"技术失败"伪装成"证据不足"或"语义冲突"。

### 3.5 Stage-local 五态外状态

全局 `ExtractionStatus` 五态不变。每 stage 用 stage-local enum：

| Stage | Stage-local Enum |
|---|---|
| Stage 1 | `Classification.failed / uncertain` |
| Stage 2 | `SegmentationStatus.SEGMENTED / SINGLE_EXPECTED / DEGRADED / UNCERTAIN / / failed` |
| Stage 3 | `CompletenessStatus.COMPLETE / INCOMPLETE / UNCERTAIN / TECHNICAL_FAILURE` |
| Stage 4 | `ClusterStatus.CLUSTERED / DEGRADED / UNCERTAIN / FAILED / EMPTY` |
| Stage 5 | `FillStatus.FILLED / PARTIAL / INSUFFICIENT / CONFLICTING / COHERENCE_FAILED / TECHNICAL_FAILURE` |
| Stage 6R | `RelationRunStatus.PENDING / READY / PARTIAL / FAILED / STALE` |
| Stage 7 | `CommitPhase.PREPARED / STAGING / PUBLISHING / INDEXING / CHECKPOINTING / FINALIZING / COMMITTED / FAILED / RECONCILED` |
| Reconciliation | `ReconciliationStatus.PENDING / ACTIVE / STALE / TOMBSTONED` |

---

## 4. Tasks（按依赖顺序）

每个 task 一个 logical slice。`Status: pending` 是默认；进入编码阶段后按 TDD 流程：test → impl → verify → commit。

---

### Task 1: Stage 1 — doc_classifier 整改（止血）

**Files**:
- `src/pipeline/v7_extract/doc_classifier.py`
- `src/pipeline/v7_extract/topic_clusterer.py`（消费者声明，见 F12 整改）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage1.py` 新增测试：
  - `test_failed_field_added_when_llm_timeout`
  - `test_uncertain_field_distinguished_from_failed`
  - `test_traits_field_replaces_single_enum`
  - `test_evidence_summary_records_coverage`
  - `test_classifier_fingerprint_computed`
  - `test_incomplete_value_removed_from_valid_types`
  - `test_traits_consumed_by_stage4_classification_hint`（**F12 整改要求** — traits 必须有显式消费者：Stage 4 cluster_topics 接收 classification_hint，Hint dataclass 含 traits 字段，且 `if "possible_collection" in traits: stronger_structural_signal`）

**Implementation**:
- `__slots__` 扩展：`(doc_type, confidence, rationale, failed, error, uncertain, traits, evidence_summary, classifier_fingerprint)`
- `_VALID_DOC_TYPES` 删除 `"incomplete"`（保留 `single_method / multi_section / collection / qa_chat / list / tool / mixed`）
- `DocType.INCOMPLETE` enum 删除（不再 import）
- 失败路径 (`:184-186`) 改为显式 `failed=True, error=str(last_error)`，不再伪装成 `incomplete`
- `_payload_to_result` 增加 `traits` / `uncertain` / `evidence_summary` / `classifier_fingerprint` 字段
- `evidence_summary` 由 `_build_evidence_pack` 返回（HEAD/TAIL + h2_count / author_marker_count / qa_marker_count）

**Acceptance**:
- 现有 `tests/test_v7_extract_*` 全绿（298 passed + 1 skipped）
- 新增 6 条测试全绿
- `grep -rn 'DocType.INCOMPLETE' src/` 返回 0 结果
- `grep -rn '"incomplete"' src/pipeline/v7_extract/doc_classifier.py` 返回 0 结果
- `python -m src.cli classify-fixture test.md --dry-run` 能返回 `traits` 字段

**Status**: pending

---

### Task 2: Stage 1 失败入队分支（止血）

**Files**:
- `scripts/extract_pilot.py`

**Test**:
- `tests/test_scripts/test_extract_pilot.py` 新增：
  - `test_stage1_failed_routes_to_review_queue`
  - `test_stage1_failed_does_not_proceed_to_stage3`

**Implementation**:
- `_extract_one`（`extract_pilot.py:188` 之后）增加：
  ```python
  if classification.failed:
      _record_failure(relative, "stage1",
                     reason=f"stage1_llm_failed: {classification.error}",
                     content_hash=source_md5)
      return ExtractionResult(status=ExtractionStatus.FAILED, ...)
  ```

**Acceptance**:
- Stage 1 失败不再进入 Stage 3
- failure 记录进 reviews queue
- 现有 Stage 1 失败路径测试仍绿

**Status**: pending

---

### Task 3: Stage 2 — SegmentationResult contract + invariants

**Files**:
- `src/pipeline/v7_extract/segmentation.py`（新建）
- `src/pipeline/v7_extract/invariants.py`（新建）
- `scripts/extract_pilot.py`（改 Stage 2 调用入口）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage2.py`：
  - `test_segmentationresult_carries_coverage_and_invariants`
  - `test_invariant_validator_rejects_overlapping_spans`
  - `test_invariant_validator_rejects_uncovered_gaps`
  - `test_single_expected_status_for_truly_single_doc`
  - `test_uncertain_status_for_ambiguous_structure`

**Implementation**:
- 新增 `SegmentationStatus`（SEGMENTED / SINGLE_EXPECTED / DEGRADED / UNCERTAIN / FAILED）
- 新增 `CanonicalItem`（`item_id / kind / start_byte / end_byte / title / text / boundary_sources / confidence / display_index`）
- 新增 `CoverageReport` + `InvariantReport`（5 条 invariant）
- `_extract_items_async`（`extract_pilot.py:495`）重构：
  - 永远先跑 `_extract_items_by_metadata_header`（已存在）
  - 永远再跑 `_extract_items_by_author_byline`（新增，见 Task 4）
  - 不再依赖 `doc_type == "collection"` 门控（替换为结构信号，见 Task 4）

**Acceptance**:
- 现有 Stage 2 测试全绿
- 新增 5 条测试全绿
- `grep -rn 'doc_type == "collection"' scripts/extract_pilot.py` 返回 0 结果

**Status**: pending

---

### Task 4: Stage 2 — 去除 Stage 1 硬门 + 作者署名确定性切分器

**Files**:
- `scripts/extract_pilot.py`
- `src/pipeline/v7_extract/structural_scanner.py`（新建，先放最小版）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage2.py`：
  - `test_author_byline_deterministic_split_works_without_collection_doc_type`
  - `test_stage2_runs_even_when_doc_type_wrong`（Stage 1 故意错分类时仍能识别强结构）
  - `test_first_match_wins_replaced_with_strong_weak_invalid_classification`

**Implementation**:
- 新增 `_AUTHOR_BYLINE_RE` 与 `_extract_items_by_author_byline`
- `_extract_items_async` 重构顺序：metadata_header → author_byline → LLM window resolver → v2 fallback
- 引入最小版 `_looks_like_collection`（基于结构信号，不基于 Stage 1 doc_type）
- 现阶段 `StructuralScanner` 留 Task 7 第二批；本 Task 只确保结构性切分逻辑完整

**Acceptance**:
- Stage 1 故意错分类（`multi_section` 但实际是 collection）→ Stage 2 仍能切分
- 现有 Stage 2 测试全绿

**Status**: pending

---

### Task 5: Stage 2 — UTF-8 byte offset 坐标系统一

**Files**:
- `src/pipeline/v7_extract/segmentation.py`
- `src/pipeline/v7_extract/article_segmenter.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage2.py`：
  - `test_byte_offset_against_utf8_source_bytes`
  - `test_chinese_string_byte_offset_consistent`
  - `test_chinese_byte_offset_slice_consistent`（**F5 整改要求** — 必须验证中文 byte slice 与 char slice 一致；fixture："知识"在 UTF-8 是 6 bytes，Python len 是 2 chars；byte offset 切 span 不能错位）
  - `test_article_boundary_slice_bytes_returns_correct_text`（**F5 整改要求**）
  - `test_canonical_span_byte_offset_against_item_relative_consistent`（**FP10 加固** — item-relative vs source-absolute 不混淆）

**Implementation**:
- `CanonicalItem.start_byte / end_byte` 改为 UTF-8 byte offset against **original source bytes**
- **重写 `ArticleBoundary.slice` 方法**（**F5 整改要求**）：
  ```python
  # 旧: def slice(self, content: str) -> str: return content[self.start:self.end]
  # 新 (双方法，明确区分 byte vs char):
  def slice_bytes(self, source_bytes: bytes) -> bytes:
      return source_bytes[self.start_byte:self.end_byte]
  def slice_text(self, source_bytes: bytes) -> str:
      return self.slice_bytes(source_bytes).decode("utf-8", errors="replace")
  # 保留旧 slice(content) 方法但标记 deprecated，warn 一旦调用
  ```
- **byte offset 坐标系严格文档（**FP10 加固**）**：
  - `CanonicalItem.start_byte / end_byte` = **source bytes offset**（原始文件字节位置）
  - `item.text` = decoded string（同一 start_byte/end_byte 区间）
  - Stage 5 `CanonicalSpan.start_byte / end_byte` = **source-absolute offset**（同样是原始文件字节位置）
  - **已冻结决议（Task 14 实施，2026-09-17）**：`CanonicalSpan` 采用 source-absolute，使 `source_bytes[span.start_byte:span.end_byte]` 无需任何算术即正确。每个消费者都要切片 `source_bytes`，item-relative 会让算术分散到各处。
    - 曾考虑的 item-relative 方案已否决（原文 §398-400 措辞已由本节取代）
    - item-local 视图保留在 `CanonicalSpan.char_start / char_end`（`item.text` 内的字符偏移）
    - 两种视图必须描述同一段文本 —— 由 `test_canonical_span_byte_offset_against_item_relative_consistent` 锁定（fixture `item.start_byte=100` + CJK 3 字节/字符，并断言 `span.start_byte - item.start_byte != span.char_start` 以证明两个坐标系确实不同）
  - 错误使用示例：把 `item.text` 的 char 下标当作 source byte 下标使用 → **切错位置**
- 现有 `len(content)` 字符索引逻辑保留作为 char offset 派生（用于回退）
- 明确文档：`byte offset ≠ character offset`，Python string 按 char 索引，UTF-8 多字节字符需 encode 转换
- `ArticleBoundary.start/end` 同步改为 `start_byte/end_byte`

**Acceptance**:
- 中文 source 测试 fixture：byte span 切出的 substring 与 char slice 一致
- **F5 硬指标**：`test_chinese_byte_offset_slice_consistent` 必须绿（否则 Stage 5 整改不可行）
- 现有 Stage 2 测试全绿

**Status**: pending

---

### Task 6: Stage 3 — CompletenessResult + 技术失败分离

**Files**:
- `src/pipeline/v7_extract/completeness_checker.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage3.py`：
  - `test_technical_failure_returns_none_not_false`
  - `test_uncertain_status_distinguished_from_incomplete`
  - `test_completenessresult_carries_evidence_refs`
  - `test_hard_invariant_technical_failure_never_mapped_to_incomplete`

**Implementation**:
- 新增 `CompletenessStatus`（COMPLETE / INCOMPLETE / UNCERTAIN / TECHNICAL_FAILURE）
- 新增 `CompletenessResult`（status / reason_codes / evidence_refs / confidence / checker_fingerprint / warnings / technical_error）
- `check_completeness` 失败时返回 `None`（不再 `(False, "stage3_failed_...")` 假装 incomplete）
- `_payload_to_result` 增加 `uncertain` 分支（LLM 评估为 ambiguous）
- Script resolver：`assessment → status` 映射表（不强 trust LLM）

**Acceptance**:
- LLM timeout 返回 `None`（不是 `CompletenessStatus.INCOMPLETE`）
- 关键回归测试：`test_hard_invariant_technical_failure_never_mapped_to_incomplete` 必须绿（这是 Stage 3 整改的硬指标 0）

**Status**: pending

---

### Task 7: Stage 3 — bounded evidence pack + 消费 Stage 2 结构

**Files**:
- `src/pipeline/v7_extract/completeness_checker.py`
- `src/pipeline/v7_extract/prompts/builtin/completeness.toml`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage3.py`：
  - `test_evidence_pack_includes_head_tail_and_stage2_signals`
  - `test_completeness_consumes_stage2_structural_summary`
  - `test_long_doc_does_not_truncate_observation`
  - `test_evidence_pack_includes_middle_samples`（**FP2 加固要求** — Round 2 极简加固）

**Implementation**:
- 新增 `_build_completeness_evidence(content, stage2_summary, fingerprint)`：
  - HEAD/TAIL 各 2000 bytes
  - **3 个中段采样（**FP2 加固**）**：每个 500 bytes，位置 25%/50%/75%
  - Stage 2 结构信号（item_count / last_item_truncated / boundary_confidence / status）
  - 硬预算 4000 bytes
  - 总开销：HEAD(2000) + TAIL(2000) + 3×MID(500) = 5500 bytes（**fp2 加固后预算微调**，可接受）
- prompt 改为受控 evidence pack（不再 `content[:8000]`）
- Stage 2 → Stage 3 接口（`StructuralSummary`）：

**Acceptance**:
- 100KB 长 source：Stage 3 输入 ≤ 5500 bytes，不会因 LLM context 截断而误判
- **FP2 加固**：中部 3 个采样点存在，LLM 不再仅凭 HEAD/TAIL 误判
- 现有 Stage 3 测试全绿

**Status**: pending

---

### Task 8: Stage 3 — checkpoint 双键（` proven_incomplete` only skip）

**Files**:
- `scripts/extract_full.py`

**Test**:
- `tests/test_scripts/test_extract_full.py`：
  - `test_incomplete_only_skips_when_fingerprint_matches`
  - `test_failed_or_blocked_never_skipped`

**Implementation**:
- `_source_can_skip`（`extract_full.py:499`）改为：
  ```python
  if status == ExtractionStatus.INCOMPLETE.value:
      prior_fp = prior.get("completeness_fingerprint", "")
      current_fp = current_checker_fingerprint()
      if prior_fp and prior_fp != current_fp:
          return False  # checker 升级 → 重新判断
      return True
  ```
- `failed` / `blocked` 永远不 skip（与 Stage 2 一致）

**Acceptance**:
- checker 升级后，相同 source md5 仍会重判 incomplete
- failed 状态即使多次也不被 skip

**Status**: pending

---

### Task 9: Stage 4 — ClusterResult contract + ClusterStatus

**Files**:
- `src/pipeline/v7_extract/topic_clusterer.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage4.py`：
  - `test_max_topics_no_longer_semantic_limit`
  - `test_clusterresult_carries_metrics`
  - `test_quality_gate_blocks_umbrella_topic`
  - `test_clusterstatus_failed_distinct_from_degraded`
  - `test_article_loss_strict_threshold_with_diagnostic`（**F9 整改要求** — 阈值 0.85 + diagnostic）

**Implementation**:
- 新增 `ClusterStatus`（CLUSTERED / DEGRADED / UNCERTAIN / FAILED / EMPTY）
- 新增 `ClusterMetrics`（9 个指标：`item_count / topic_count / items_per_topic / unresolved_item_ratio / unresolved_byte_ratio / unresolved_article_ratio`（**FP3 加固**） / `singleton_topic_ratio / largest_topic_share / article_preservation_ratio / duplicate_assignment_ratio`）
- 新增 `ClusterResult`（status / topics / unresolved / metrics / warnings / clusterer_fingerprint）
- 删除 `max_topics=20` 语义上限（改为工程预算 `MAX_CLUSTER_CALLS_PER_SOURCE=10`）
- Stage 1 doc_type 降为 `classification_hint`（soft hint，不门控）
- **UNCERTAIN 阈值放宽（**F9 整改要求**）**：
  - 旧：`article_preservation_ratio < 0.95` → UNCERTAIN
  - 新：`article_preservation_ratio < 0.85` → UNCERTAIN
  - 增加 diagnostic metric：`article_preservation_diagnostic: str` —— 区分"真正丢失"（article item 在 segmentation 里消失）vs "stage 4 没识别"（article item 存在但 topic 没接）
  - `article_preservation_diagnostic` 字段：`"none_lost"`（保留全部） / `"stage4_missed"`（seg 有 article 但 topic 没接） / `"actually_lost"`（seg 也没有 article）

**Acceptance**:
- 50 个 items 不再被压成 ≤ 20 topics
- `largest_topic_share > 0.5` 触发 `ClusterStatus.DEGRADED`
- `article_preservation_ratio < 0.85` 触发 `ClusterStatus.UNCERTAIN`（**F9 放宽**）
- diagnostic metric 区分"stage4_missed" vs "actually_lost"
- **FP3 加固**：`unresolved_article_ratio > 0.1` 触发 `ClusterStatus.DEGRADED`（专门跟踪 article item 漏接）
- 现有 Stage 4 测试全绿

**Status**: pending

---

### Task 10: Stage 4 — TopicCandidate + 解除 single-topic-per-item 硬约束

**Files**:
- `src/pipeline/v7_extract/topic_clusterer.py`
- `src/pipeline/v7_extract/topic_candidate.py`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage4.py`：
  - `test_one_item_multiple_topic_candidates`
  - `test_topic_candidate_id_is_script_generated`
  - `test_collection_one_article_may_produce_multiple_topics`

**Implementation**:
- 新增 `TopicCandidate`（candidate_id / item_index / local_index / semantic_label / evidence_span_hint / confidence）
- `_payload_to_topics`（`topic_clusterer.py:177-180`）解除"同 item_index 重复 → raise"硬约束：
  - 同 item 内多个 candidate 用 distinct local_index 区分
- `derive_candidate_id(item_index, local_index, span_hint, item_fingerprint)` 脚本生成

**Acceptance**:
- 1 个 item 内 5 个知识主题 → 5 个 TopicCandidate（不再被压成 1 topic）
- candidate_id 由脚本生成（不依赖 LLM label）

**Status**: pending

---

### Task 11: Stage 4 — 两阶段 LLM（discovery → grouping）+ Stage 2 消费

**Files**:
- `src/pipeline/v7_extract/topic_clusterer.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage4.py`：
  - `test_stage4a_discovers_per_item_candidates`
  - `test_stage4b_groups_candidates_across_items`
  - `test_clustering_consumes_stage2_structural_summary`

**Implementation**:
- 拆 `cluster_topics` 为 `_discover_topics_in_batch` + `_group_candidates`
- `cluster_topics` 输入增加 `segmentation_result`（Stage 2 消费）
- Stage 1 doc_type 仅作 hint；Stage 2 structural_summary 优先

**Acceptance**:
- Stage 1 错分类（collection → multi_section）时，Stage 4 仍按 Stage 2 结构分组
- 现有 Stage 4 测试全绿

**Status**: pending

---

### Task 12: Stage 4 — topic_id 脚本生成（切断 LLM 依赖）

**Files**:
- `src/pipeline/v7_extract/topic_clusterer.py`
- `scripts/extract_pilot.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage4.py`：
  - `test_topic_id_is_deterministic_hash_not_llm_label`
  - `test_page_id_derived_from_script_generated_topic_id`

**Implementation**:
- `Topic.id` 改为 `derive_topic_id(source_id, candidate_ids, semantic_label)`：
  - identity = `source_id | sorted(candidate_ids)`
  - label 不进 identity（label 可变，identity 不变）
- 修改 `_stable_page_id(relative, topic.id)` 调用（`extract_pilot.py:289`）使用新的 topic.id

**Acceptance**:
- 同一语义不同 LLM label → 同一 topic_id
- topic_id 形如 `<source_id>-topic-<16hex>`

**Status**: pending

---

### Task 13: Stage 4 — `__other__` 改 unresolved signal

**Files**:
- `src/pipeline/v7_extract/topic_clusterer.py`
- `scripts/extract_pilot.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage4.py`：
  - `test_unresolved_ratio_appears_in_metrics`
  - `test_other_topic_preserved_as_blocked_but_metrics_emitted`

**Implementation**:
- `ClusterResult.unresolved` 字段替代 __other__ 简单塞入
- `to_legacy_topics` 仍生成 `__other__` Topic（兼容 Stage 7 旧 gate）
- `extract_pilot.py:316` gate 不变；附加 review_reasons 含 `unresolved_ratio` metric

**Acceptance**:
- unresolved_ratio > 0.3 触发 review signal
- Stage 7 旧 `__other__` gate 仍工作（向后兼容）

**Status**: pending

---

### Task 14: Stage 5 — Claim/EvidenceRef 数据结构 + canonical spans

**Files**:
- `src/pipeline/v7_extract/claim.py`（新建）
- `src/pipeline/v7_extract/canonical_spans.py`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage5.py`：
  - `test_claim_carries_evidence_refs_with_byte_spans`
  - `test_canonical_spans_built_from_canonical_item_byte_range`

**Implementation**:
- 新增 `Claim`（claim_id / slot_name / text / evidence_refs / support / confidence / risk）
- 新增 `EvidenceRef`（item_id / item_index / span_index / start_byte / end_byte；`excerpt_from(source_bytes)` 派生）
- 新增 `ClaimSupport`（SUPPORTED / NOT_APPLICABLE / INSUFFICIENT_EVIDENCE / CONFLICTING）
- 新增 `ClaimRisk`（LOW / HIGH — 数字/否定/因果/比较）
- 新增 `CanonicalSpan`（`build_canonical_spans(items, head_bytes=1500, overlap_bytes=200)`）

**Acceptance**:
- 1 slot 内可有 0..N 个 Claim
- 每个 Claim 至少 1 个 EvidenceRef（substantive claim）

**Status**: pending

---

### Task 15: Stage 5 — Stage 5A claim extraction（先证据后 claim）

**Files**:
- `src/pipeline/v7_extract/claim_extractor.py`（新建）
- `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage5.py`：
  - `test_extract_slot_claims_returns_evidence_backed_claims`
  - `test_llm_returns_span_indexes_not_byte_offsets`
  - `test_high_risk_claims_detected_by_regex`

**Implementation**:
- `extract_slot_claims(slot_name, *, topic_label, spans, llm, template, source_bytes)`：
  - 喂给 LLM 候选 spans（含 excerpt）
  - LLM 返回 `(claim_text, span_ids[])`
  - 脚本映射 span_ids → canonical spans → byte offsets
  - 风险评估（脚本正则：`\d+\.?\d*\s*%`、`提高/降低`、`适合/不适合`、`导致/由于`、`优于/劣于`）
- 修改 `fill_slots.toml`：从生成 page → 改为生成 claims

**Acceptance**:
- LLM 返回 `(text, span_ids[])`，不返回 byte offset
- high-risk claims 标 `ClaimRisk.HIGH`

**Status**: pending

---

### Task 16: Stage 5 — Claim validator（10 条 mechanical invariants）

**Files**:
- `src/pipeline/v7_extract/claim_validator.py`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage5.py`：
  - `test_validator_rejects_evidence_outside_item_span`
  - `test_validator_rejects_cross_topic_evidence`
  - `test_validator_rejects_evidence_span_too_long`
  - `test_filter_substantive_claims_drops_unsupported`

**Implementation**:
- `validate_claim(claim, *, topic_items, topic_id)` 返回 `ClaimValidationReport`
- 10 条 mechanical invariants：
  1. substantive claim ≥ 1 evidence
  2. evidence ref 属于 topic
  3. evidence span 落在 item 内
  4. no cross-topic evidence
  5. evidence refs 不重复
  6. claim ID 唯一
  7. 所有 substantive claims 有 evidence
  8. 不允许跨 topic evidence
  9. 不允许引用 `__other__`
  10. evidence span 长度合理（30-3000 bytes）

**Acceptance**:
- evidence span 越界 → 验证失败
- evidence 跨 topic → 验证失败

**Status**: pending

---

### Task 17: Stage 5 — Semantic reviewer（high-risk claims）

**Files**:
- `src/pipeline/v7_extract/claim_reviewer.py`（新建）
- `src/pipeline/v7_extract/prompts/builtin/claim_reviewer.toml`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage5.py`：
  - `test_reviewer_rejects_contradicted_claim`
  - `test_reviewer_only_invoked_for_high_risk`
  - `test_reviewer_failure_demotes_claim_to_insufficient`

**Implementation**:
- `review_high_risk_claims(claims, *, source_bytes, llm, template)`
- 仅审 `risk == HIGH` 的 claim
- Verdict：SUPPORTED / CONTRADICTED / INSUFFICIENT / AMBIGUOUS
- CONTRADICTED → `claim.support = INSUFFICIENT_EVIDENCE`（不允许写盘）
- reviewer 失败 → high-risk claims 全部降级 INSUFFICIENT

**Acceptance**:
- 数字 claim（"提高 10%"）若被 reviewer 判 CONTRADICTED → 不进入 page
- reviewer 故障 → high-risk claims 不进入 page（fail-closed）

**Status**: pending

---

### Task 18: Stage 5 — Stage 5B deterministic page synthesis + FillResult

**Files**:
- `src/pipeline/v7_extract/page_synthesizer.py`（新建）
- `src/pipeline/v7_extract/slot_filler.py`（重构）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage5.py`：
  - `test_synthesize_slot_drops_unsupported_claims`
  - `test_fillresult_status_mapping_to_extraction`
  - `test_legacy_concept_page_still_generated_for_stage7`

**Implementation**:
- `synthesize_slot(slot_name, claims)` 把 supported claims 渲染为 Markdown
- 新增 `FillResult`（topic_id / status / slots / needs_review_slots / metrics / generator_fingerprint / warnings / technical_error / legacy_page）
- 新增 `FillStatus`（FILLED / PARTIAL / INSUFFICIENT / CONFLICTING / COHERENCE_FAILED / TECHNICAL_FAILURE）
- `map_fill_to_extraction(fill)` 把 FillStatus 映射到 ExtractionStatus 五态：
  - TECHNICAL_FAILURE → FAILED（retry）
  - INSUFFICIENT / COHERENCE_FAILED → BLOCKED（review）
  - FILLED / PARTIAL / CONFLICTING → WRITTEN（`metrics.topic_completion_ratio < 0.4` 例外 → BLOCKED）
- `fill_slots_v2` 主入口：旧 `fill_slots` 保留为 legacy adapter

**Acceptance**:
- 关键回归：technical failure 永远不映射到 `WRITTEN`
- 旧 `fill_slots` 测试仍绿（向后兼容）

**Status**: pending

---

### Task 19: Stage 7 — CommitManifest + 阶段机（crash consistency）

**Files**:
- `src/pipeline/v7_extract/commit_manifest.py`（新建）
- `src/pipeline/v7_extract/wiki_writer.py`（重构）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage7.py`：
  - `test_manifest_persists_at_each_phase`
  - `test_reconcile_unfinished_commits_handles_partial_state`
  - `test_idempotent_page_commit_skips_when_revision_hash_matches`

**Implementation**:
- 新增 `CommitPhase`（PREPARED / STAGING / PUBLISHING / INDEXING / CHECKPOINTING / FINALIZING / COMMITTED / FAILED / RECONCILED）
- 新增 `CommitManifest` + `PageCommitRecord`
- `commit_and_index` 改造流程：
  1. Create manifest (PREPARED)
  2. Process pages (PUBLISHING)
  3. Update index (INDEXING)
  4. Write checkpoint (CHECKPOINTING)
  5. Mark COMMITTED
- `reconcile_unfinished_commits()` 启动时调用：扫描未完成 manifest，校验 page file 是否存在 + hash 匹配
  - **FP6-minimal 加固**：增加 hash mismatch 校验（`if self._hash_file(path) != record.revision_hash: 标 failed`），仅 +1 行

**Acceptance**:
- 进程死在 `publish page` 之前 → 重启后 page 状态可 reconcile
- 进程死在 `index` 之前 → page 已写但 index pending，reconcile 时补齐

**Status**: pending

---

### Task 20: Stage 7 — Page frontmatter ownership + revision_hash

**Files**:
- `src/pipeline/v7_extract/wiki_writer.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage7.py`：
  - `test_page_frontmatter_has_owner_v7`
  - `test_page_frontmatter_has_revision_hash`
  - `test_page_frontmatter_has_pipeline_fingerprint`

**Implementation**:
- `_write_page_atomically` 增加 frontmatter 字段：
  - `owner: v7`
  - `pipeline: v7`
  - `commit_id: <manifest.commit_id>`
  - `pipeline_fingerprint: <from constructor>`
  - `revision_hash: <sha1 of rendered content>`
  - `committed_at: <unix ms>`

**Acceptance**:
- 每个 page frontmatter 含全部 6 个新字段
- 旧 page 仍可读（向后兼容）

**Status**: pending

---

### Task 21: Stage 7 — Durable failure fact + review queue 降级

**Files**:
- `src/pipeline/v7_extract/wiki_writer.py`

**Test**:
- `tests/test_pipeline/test_v7_extract_stage7.py`：
  - `test_durable_failure_log_written_before_review_queue`
  - `test_review_queue_projection_failure_marks_pending`
  - `test_durable_facts_survive_queue_io_failure`
  - `test_durable_failure_does_not_pollute_reviews_queue`（**F11 整改要求** — 明确分工）

**Implementation**:
- 新增 `.index/durable_failure.jsonl` 路径
- **明确分工（**F11 整改要求**）**：
  - `durable_failure.jsonl` **仅记录 stage 7 page-level outcome**（committed/blocked/failed，**含全部结果**）
  - `reviews_queue.json` **仅记录需要人工 review 的不确定事件**（语义冲突 / coherence_failed / uncertain，**仅含 review-needed**）
  - 两者不重叠：committed 不进 reviews_queue，uncertain 不进 durable_failure
- `_record_durable_outcome(record)` 在 queue projection 之前写 durable failure（每个 page outcome 都写）
- `_project_failures_to_review_queue(manifest)` 在 durable fact 之后投影（**仅 status in {BLOCKED, UNCERTAIN, CONFLICTING}**）
- queue projection 失败 → 写入 `.index/queue_projection_pending.jsonl`（repair job 可消费）

**Acceptance**:
- queue I/O 失败时 durable failure 仍存在
- queue projection pending log 可被修复 job 重建
- **F11 硬指标**：`test_durable_failure_does_not_pollute_reviews_queue` 必须绿（reviews_queue.json 不含 committed records）

**Status**: pending

---

### Task 22: Stage 7 — Source checkpoint 接入 pipeline_fingerprint

**Files**:
- `scripts/extract_full.py`

**Test**:
- `tests/test_scripts/test_extract_full.py`：
  - `test_source_skip_requires_pipeline_fingerprint_match`
  - `test_pipeline_upgrade_triggers_re_evaluation`

**Implementation**:
- `_source_outcome_from_result` 增加 `pipeline_fingerprint` 字段
- `_source_can_skip` 改为：
  ```python
  if status in {WRITTEN, ...}:
      if prior.get("pipeline_fingerprint") != current_pipeline_fingerprint():
          return False  # pipeline 升级 → 重跑
      ...
  ```

**Acceptance**:
- pipeline 升级后相同 source md5 仍触发重判
- pipeline 不变 + source 不变 → 仍可 skip（向后兼容旧 checkpoint 无 fingerprint）

**Status**: done (pre-empted by Stage 3 Task 8, commit `a84e1c11`)

> **Done by Stage 3.** `a84e1c11 feat(stage3): checkpoint double-key` already
> implemented the pipeline_fingerprint double-key semantics: `_source_outcome_from_result`
> (line 451), `_source_can_skip` (line 568), and `_current_pipeline_fingerprint`
> (line 455). The acceptance tests are also in place under different names:
> `test_incomplete_only_skips_when_fingerprint_matches`,
> `test_source_outcome_from_result_records_pipeline_fingerprint`,
> `test_current_pipeline_fingerprint_is_stable_and_order_independent`,
> `test_current_pipeline_fingerprint_changes_with_any_input`. All 7 fingerprint
> tests pass at `a84e1c11..HEAD`.

---

### Task 23: Stage 6R — RelationPredicate ontology + RelationKey

**Files**:
- `src/pipeline/v7_extract/relation_ontology.py`（新建）
- `src/pipeline/v7_extract/relation_models.py`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage6.py`：
  - `test_relation_predicate_enum_matches_wiki_ontology`
  - `test_relation_key_canonicalizes_symmetric_relations`
  - `test_relation_id_is_deterministic_hash`
  - `test_relations_remain_in_wiki_frontmatter_as_best_effort_view`（**F8 决策回退** — relations 仍写入 frontmatter，RelationStore 是权威源）

**Implementation**:
- 新增 `RelationPredicate` enum（13 个 predicate + UNRESOLVED）
- 新增 `RelationTypeSpec`（directional / symmetric / inverse_predicate / high_risk）
- 新增 `RelationKey`（source_page_id / predicate / target_page_id） + `canonicalize()` 处理对称关系
- 新增 `RelationAssertion`（key / relation_id / support_kind / support_status / evidence_refs / claim_ids / confidence / extractor_fingerprint）
- **F8 决策回退（奥卡姆剃刀）**：relations 仍写入 Wiki frontmatter
  - `_write_page_atomically` **保留** `_last_relations` 注入（`wiki_writer.py:254-260` 不动）
  - frontmatter relations 是 **best-effort 视图**（reader 不需要改造）
  - `RelationStore.relations.jsonl` 是 **权威源**（lifecycle / reconciliation 走 RelationStore）
  - 两套数据流并存，但用途清晰**——零 reader 改造 blast radius**

**Acceptance**:
- `A related_to B` 与 `B related_to A` 同一 relation_id
- `A depends_on B` 与 `B depends_on A` 不同 relation_id
- **F8 回退验收**：`test_relations_remain_in_wiki_frontmatter_as_best_effort_view` 必须绿（frontmatter relations 字段存在，RelationStore 是权威源）

**Status**: pending

---

### Task 24: Stage 6R — RelationStore + independent checkpoint

**Files**:
- `src/pipeline/v7_extract/relation_store.py`（新建）
- `src/cli_ext/relation_cmd.py`（新建）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage6.py`：
  - `test_relation_store_persists_per_page`
  - `test_cascade_page_delete_tombstones_edges`
  - `test_page_update_triggers_relation_recompute`

**Implementation**:
- 新增 `RelationStore`（独立 checkpoint `.index/relation_run_state.json`）
- 新增 `RelationRunRecord`（page_id / page_revision / relation_ids / status / attempts / last_error / extractor_fingerprint）
- `apply_result(result)` 用 desired snapshot + diff：
  - 删旧该 page 的 relations
  - 加新的
  - 记录 tombstone
- `cascade_page_delete(page_id)` 级联 tombstone 所有 inbound/outbound edges
- 新增 CLI：`reconcile-relations` / `show-relations <page_id>`

**Acceptance**:
- relation checkpoint 与 source checkpoint 完全独立
- page 删除后所有相关 edges 进入 tombstone（不残留 dangling）

**Status**: pending

---

### Task 25: Stage 6R — Candidate retrieval + LLM 受控 ontology

**Files**:
- `src/pipeline/v7_extract/candidate_retrieval.py`（新建）
- `src/pipeline/v7_extract/relation_extractor.py`（重构）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage6.py`：
  - `test_candidate_retrieval_returns_top_n`
  - `test_llm_cannot_invent_predicate`
  - `test_explicit_vs_inferred_kind_distinguished`

**Implementation**:
- 6 种 retrieval 策略：
  1. 显式 wikilink
  2. entity overlap (Jaccard)
  3. lexical match
  4. acronym match (RAG ↔ Retrieval-Augmented Generation)
  5. alias dictionary lookup
  6. vector neighbor (optional)
- 上限 `MAX_CANDIDATES_PER_PAGE = 30`
- LLM 输入受控 ontology（不能选 UNRESOLVED 之外的非法 predicate）
- `RelationSupportKind`（EXPLICIT / INFERRED / LLM_DIRECT / HEURISTIC）

**Acceptance**:
- 10000 pages 不再 O(N²)
- LLM 返回非法 predicate → 标 `RelationSupportStatus.UNRESOLVED`

**Status**: pending

---

### Task 26: Stage 6R — Mechanical validator + 12 invariants

**Files**:
- `src/pipeline/v7_extract/relation_models.py`（增加 validator）

**Test**:
- `tests/test_pipeline/test_v7_extract_stage6.py`：
  - `test_validator_rejects_unknown_target`
  - `test_validator_rejects_invalid_predicate`
  - `test_validator_rejects_self_edge_for_directional_predicate`

**Implementation**:
- `_validate_relations(relations, all_pages, config)` 返回 `(validated, rejected, unresolved)`
- 12 条 invariants（你的 Stage 6 整改 §21）

**Acceptance**:
- 12 条 invariant 全部覆盖
- 不通过验证的 relation 进入 rejected，不进入 store

**Status**: pending

---

### Task 27: Reconciliation — Canonical models + Decision enum

**Files**:
- `src/reconciliation/canonical_models.py`（新建）

**Test**:
- `tests/test_reconciliation/test_canonical_models.py`：
  - `test_canonical_id_format_is_uuid_based`
  - `test_reconciliation_decision_enum_has_eight_values`
  - `test_aliasrecord_supports_multilingual`

**Implementation**:
- 新增 `ReconciliationDecision`（SAME / ALIAS / BROADER / NARROWER / OVERLAP / CONFLICT / DISTINCT / UNRESOLVED）
- 新增 `ReconciliationStatus`（PENDING / ACTIVE / STALE / TOMBSTONED）
- 新增 `CanonicalConcept`（canonical_id / preferred_label / aliases / member_page_ids / status / resolver_fingerprint / version / claim_ids / relation_ids）
- 新增 `AliasRecord`（alias_text / canonical_id / language / provenance / resolver_fingerprint）
- 新增 `ReconciliationDecisionRecord`（decision_id / candidate_page_id / candidate_canonical_id / decision / confidence / reason / evidence_refs / resolver_fingerprint）
- `new_canonical_id()` 返回 `c_<uuid4[:16]>`

**Acceptance**:
- canonical_id 与 preferred_label 完全解耦
- UNRESOLVED 是合法 decision（不强制合并）

**Status**: pending

---

### Task 28: Reconciliation — Candidate retrieval 6 策略

**Files**:
- `src/reconciliation/candidate_retrieval.py`（新建）

**Test**:
- `tests/test_reconciliation/test_candidate_retrieval.py`：
  - `test_retrieval_returns_top_n_candidates`
  - `test_acronym_match_finds_RAG_alias`
  - `test_embedding_similarity_only_signals_worth_comparing_not_merge`
  - `test_vector_neighbor_retrieval_integration`（**F10 整改要求** — 第一批必须含 vector_neighbor）
  - `test_vector_neighbor_performance_under_10k_canonical`（**F10 整改要求** — < 100ms）

**Implementation**:
- **6 种 retrieval 策略全部进第一批**（**F10 整改要求** — vector_neighbor 不可留第二批）：
  1. 显式 wikilink
  2. entity overlap (Jaccard)
  3. lexical match
  4. acronym match (RAG ↔ Retrieval-Augmented Generation)
  5. alias dictionary lookup
  6. vector neighbor（复用现有 1536-dim LanceDB index）
- 上限 `MAX_CANDIDATES = 20`
- vector_neighbor 评分：`score > 0.7` 才进入候选（与 Stage 6R 一致）

**Acceptance**:
- 10000 canonical concepts 时 retrieval 仍是 O(N) 局部（不是 O(N²)）
- retrieval_score 是"值得比较"的信号，不是 merge 决策
- **F10 硬指标**：`test_vector_neighbor_performance_under_10k_canonical` < 100ms 必须绿

**Status**: pending

---

### Task 29: Reconciliation — Identity resolver + LLM 只判 decision

**Files**:
- `src/reconciliation/identity_resolver.py`（新建）
- `src/reconciliation/prompts/builtin/identity_resolve.toml`（新建）

**Test**:
- `tests/test_reconciliation/test_identity_resolver.py`：
  - `test_llm_only_returns_decision_not_canonical_id`
  - `test_llm_technical_failure_returns_unresolved`
  - `test_evidence_pack_is_controlled_not_whole_page`

**Implementation**:
- `resolve_identity(new_page, candidates, *, canonical_registry, llm, template, config)` 返回 `[ReconciliationDecisionRecord]`
- LLM 输入：受控 evidence pack（title + key_slots + evidence_refs），不暴露 source-local identity
- LLM 输出：`{decision, confidence, reason, evidence_refs}`（不含 canonical_id）
- 技术失败 → 全部 UNRESOLVED

**Acceptance**:
- LLM 永不生成 canonical_id
- 技术失败映射 UNRESOLVED（不假装正常）

**Status**: pending

---

### Task 30: Reconciliation — Canonical registry + reversible membership

**Files**:
- `src/reconciliation/canonical_registry.py`（新建）
- `src/reconciliation/reconcile_job.py`（STALE 信号消费）

**Test**:
- `tests/test_reconciliation/test_canonical_registry.py`：
  - `test_apply_decisions_creates_canonical_for_distinct`
  - `test_apply_decisions_joins_existing_for_same`
  - `test_remove_membership_is_reversible`
  - `test_tombstone_when_last_member_removed`
  - `test_atomic_write_survives_crash`
  - `test_resolver_fingerprint_drift_marks_stale`（**F4 整改要求** — ①致命）
  - `test_stale_canonical_can_be_re_evaluated_incremental`（**F4 整改要求**）
  - `test_alias_single_source_of_truth`（**F15 整改要求** — 显式选 A：Reconciliation AliasRecord 调 SlugAliasRegistry adapter）

**Implementation**:
- 新增 `CanonicalRegistry`（独立路径 `.index/reconciliation/`）
- 持久化：
  - `canonical_concepts.json`（concept + status + **resolver_fingerprint** — **F4 整改要求**）
  - `alias_records.json`（alias 表）
  - `decision_log.jsonl`（每次 decision 一行）
- `apply_decisions(new_page_id, decisions, *, language, resolver_fingerprint)`：
  - 优先级 same > alias > conflict > overlap > broader/narrower > distinct > unresolved
  - DISTINCT → 新建 canonical（resolver_fingerprint 写入 cc）
  - UNRESOLVED → 不动
  - SAME / ALIAS / 其他 → 加入已有 canonical 的 membership；**更新 cc.resolver_fingerprint**
- **`reconcile_stale_concepts(current_fingerprint)`（**F4 整改要求**）**：
  - 扫描所有 active canonical
  - 若 `cc.resolver_fingerprint != current_fingerprint` → 标 `cc.status = STALE`
  - `reconcile_job` 在启动时调用 `mark_stale_concepts(current_fingerprint)`
  - 后续增量 re-evaluation 留第四批
- `remove_membership(page_id, canonical_id)`：
  - 删 member
  - 若 member_count == 0 → canonical.status = TOMBSTONED
  - 不删 page
- **AliasRecord 与 SlugAliasRegistry 整合（**F15 整改要求**）**：
  - 选项 A（采纳）：`CanonicalRegistry.add_alias` 通过 `SlugAliasRegistry` adapter 注册
  - 保留两个 storage：`canonical_concepts.json`（canonical 维度）+ `.llm-wiki/slug_aliases.json`（slug 维度）
  - Reconciliation 任务完成后**同时**更新两个存储

**Acceptance**:
- reversible membership（不破坏 page）
- 同 alias 不同 canonical → 保留第一个，不冲突覆盖
- **F4 硬指标**：`test_resolver_fingerprint_drift_marks_stale` 必须绿（resolver_fingerprint 升级后旧 canonical 自动 STALE）
- **F15 硬指标**：`test_alias_single_source_of_truth` 必须绿（alias 唯一写入路径）

**Status**: pending

---

### Task 31: Reconciliation — CLI + Phase 1 最小闭环

**Files**:
- `src/reconciliation/reconcile_job.py`（新建）
- `src/cli_ext/reconciliation_cmd.py`（新建）

**Test**:
- `tests/test_reconciliation/test_cli.py`：
  - `test_reconcile_command_processes_pages`
  - `test_show_command_displays_canonical`
  - `test_list_command_shows_active_only`
  - `test_undo_command_removes_membership`

**Implementation**:
- `reconcile_pages(pages, *, project_root, llm, template, vector_index=None, config)`：
  1. candidate retrieval per page
  2. LLM decision per page
  3. apply decisions
  4. metrics：processed / created_new / joined_existing / unresolved / errors
- CLI subcommands：
  - `reconcile --sync`：同步执行
  - `reconcile --submit`：写 pending.jsonl，后台处理
  - `show <canonical_id>`：查看 concept
  - `list`：列出所有 active canonical
  - `undo <canonical_id> <page_id>`：reversible membership 撤销

**Acceptance**:
- CLI 全命令工作
- metrics 报告含 processed / created_new / joined_existing / unresolved

**Status**: pending

---

### Task 32: 跨阶段集成测试 — 端到端 fault injection

**Files**:
- `tests/test_integration/test_v7_e2e_remediation.py`（新建）

**Test**:
- `test_e2e_normal_source_to_written_pages`（happy path）
- `test_e2e_stage1_failure_does_not_proceed`（Stage 1 → FAILED → retry）
- `test_e2e_stage3_technical_failure_not_mapped_to_incomplete`（硬指标 0）
- `test_e2e_crash_during_publish_recovers_via_manifest`（Stage 7 crash consistency）
- `test_e2e_source_update_reconciles_stale_pages`（Stage 7 lifecycle）
- `test_e2e_reconciliation_attaches_pages_to_canonical`（Reconciliation Phase 1）
- `test_e2e_unresolved_decision_does_not_force_merge`（Reconciliation 合法结果）
- `test_e2e_pipeline_upgrade_triggers_re_evaluation`（fingerprint 双键）

**Implementation**:
- fault injection：模拟 LLM timeout / 进程 crash / queue I/O 失败 / source md5 不变但 fingerprint 变
- 验证每条 invariant：committed page 文件存在 / durable failure 在 / manifest 已 reconcile

**Acceptance**:
- 所有 fault injection 场景下系统可恢复，不丢知识 / 不重复 / 不假成功
- 关键硬指标 0（技术失败 ≠ incomplete）保证

**Status**: pending

---

### Task 33: 文档同步更新（按 dev-relay §6）

**Files**:
- `docs/guides/v7-ingestion-pipeline.md`（更新 Stage 1-7 + Reconciliation 描述）
- `docs/adr/0011-v7-ingestion-outcome-control-plane.md`（追加 ADR：每个 Stage 的 stage-local enum + canonical identity + claim-level evidence）
- `docs/adr/0012-v7-knowledge-reconciliation-plane.md`（新建 ADR：reconciliation 架构）
- `docs/webui-buttons.md`（如改 web UI；本 plan 不直接改 web）

**Test**: 文档手动 review

**Implementation**:
- 主文档更新：Stage 1-7 每一节追加"Stage-local Status" / "Fingerprint" / "Bounded Evidence"
- 新增"Knowledge Reconciliation Plane"独立章节
- ADR 0011 追加：claim-level evidence / crash consistency / canonical_id 解耦
- ADR 0012 新建：reconciliation 设计原则

**Acceptance**:
- 文档与代码同步
- ADR 反映真实架构决策

**Status**: pending

---

## 5. 后续批次路线图（仅概要，待后续 plan 详细化）

### 第二批（claim reconciliation + Stage 4 reviewer + Stage 6R semantic reviewer）

- Task 34: CanonicalClaim 模型 + Phase 2 claim reconciliation
- Task 35: Stage 4 reviewer（high-risk topic candidate）
- Task 36: Stage 6R semantic reviewer（high-risk relation）
- Task 37: Stage 4 clusterer_fingerprint 接入 source checkpoint
- Task 38: Stage 5 reviewer cache（避免重复审同一 claim）
- Task 39: Stage 7 Index rebuild 命令
- Task 40: Stage 7 queue projection repair job

### 第三批（canonical claims + relations + Stage 2 StructuralScanner 完整版）

- Task 41: StructuralScanner 全量扫描（markdown / HTML / code block / boilerplate）
- Task 42: bounded LLM window resolver（替换一次性全文 LLM segmentation）
- Task 43: AnalysisView + offset mapping（HTML 解析）
- Task 44: Canonical claim projection（canonical view from member claims）
- Task 45: Stage 6R relation 基于 canonical_id（替换 page_id）

### 第四批（验收 + 长期 provenance 稳定性）

- Task 46: 每个 stage 的 gold corpus（Stage 1-7 + Reconciliation 各 ≥ 16 类）
- Task 47: Stage 4 identity stability test（rerun 同 source → 同一 topic_id）
- Task 48: Stage 5 claim_support_ratio 长期指标
- Task 49: Stage 7 fault injection 完整覆盖（6 个 crash points）
- Task 50: Reconciliation 长期 drift 监控
- Task 51: canonical_id 与 page_id 的 migration 工具（旧 page → 新 canonical）

---

## 6. Audit

### Round 1: 完成（含整改 + 复审通过）

**Round 1 审计产出**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r1.md`

**Round 1 重新评估**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r1-reassessment.md`

**Round 1 复审**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r1-review.md`

**用户决策**：不管旧 wiki、不考虑成本、只考虑未来成果能否达成。

**Round 1 结果**：✅ 通过（必修 6/6 全部到位，建议修 4/4 到位或决策明确）

### Round 2: 完成（含极简整改 + 通过）

**Round 2 压力测试产出**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r2.md`

**Round 2 多角度重新评估**：`docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan-audit-r2-reassessment.md`

**Round 2 极简整改**（奥卡姆剃刀 + 终局思维）：

| 编号 | 改动 | 来源 |
|---|---|---|
| **F8 回退** | relations 仍写入 frontmatter；RelationStore 是权威源；零 reader 改造 | 奥卡姆 |
| **FP2** | evidence pack 中部采样（3 个 500 bytes 窗口 @ 25%/50%/75%）| 必修 |
| **FP3** | `unresolved_article_ratio > 0.1` 触发 DEGRADED | 必修 |
| **FP6-minimal** | reconcile hash cross-validate（+1 行）| 极简必修 |
| **FP10** | byte offset 坐标系严格文档 + item-relative vs source-absolute 测试 | 极简必修 |

**Round 2 不修项**（多角度决策后）：

| 编号 | 不修理由 |
|---|---|
| **FP1** Stage 1 reviews queue IO 失败 | 失败不会让数据坏；简化为日志即可 |
| **FP4** reviewer invoke budget | 现有 fail-closed 已保护数据；不增加 reviewer 子系统复杂度 |
| **FP9** per-source lock file | V7 是 CLI-driven，无并发场景；加 lock 复杂度 > 价值 |

**Round 2 结果**：✅ 通过

### Human review: pending — 人工最终把关

**人工 review 重点**：
- 任务依赖顺序是否合理
- blast radius 评估是否准确
- 现有测试覆盖率是否足够
- 与现有 `SlugAliasRegistry` 的整合策略
- 整改后的硬指标测试是否覆盖关键风险点
- **F8 决策回退是否可接受**（relations 双写入 frontmatter + RelationStore）

### Open risks:

| Risk | 状态 | Mitigation |
|---|---|---|
| Topic.id 脚本化导致旧 page page_id 失效 | ✅ **已决策不修复** | 旧 wiki 不管，新 ingest 自然产生新 page_id |
| 旧 V7 checkpoint 无 fingerprint 字段 | ✅ **已决策不修复** | 旧 source 重新跑 |
| Stage 5 reviewer budget 耗尽 | ✅ **已决策**：成本不管但保留 fail-closed | Task 17 reviewer 失败 → 高风险 claims 降级 insufficient（不静默退化） |
| Stage 2 byte offset slice 切错中文 | ⚠️ **已整改** | F5 + FP10: Task 5 重写 slice 方法 + 中文 byte offset 测试 + 坐标系严格文档 |
| Stage 4 UNCERTAIN 阈值过严 → permanent stuck | ⚠️ **已整改** | F9: 阈值改为 < 0.85 + diagnostic metric；FP3 加固 `unresolved_article_ratio` |
| Stage 3 evidence pack 边界判断 → 永久 skip | ⚠️ **已整改** | FP2: 中部 3 个采样点 |
| Reconciliation canonical 爆炸（无 vector_neighbor） | ⚠️ **已整改** | F10: Task 28 vector_neighbor 进第一批 |
| Stage 7 queue projection 失败 → 审计丢失 | ⚠️ **已整改** | F11: durable_failure 先写；queue projection 失败标 pending |
| Stage 7 reconcile 不验证 hash | ⚠️ **已整改** | FP6-minimal: +1 行 hash cross-validate |
| Stage 1 traits 字段死字段 | ⚠️ **已整改** | F12: Task 1 Stage 4 显式消费 traits |
| Reconciliation fingerprint 不传播 → 旧 canonical 永不重判 | ⚠️ **已整改** | F4: Task 30 resolver_fingerprint + STALE 信号 |
| Stage 6R relations 与 Wiki reader 数据流分裂 | 🔄 **F8 决策回退** | relations 双写入 frontmatter（reader 快路径）+ RelationStore（权威源） |
| Stage 1 reviews queue IO 失败 → 审计丢失 | ✅ **已决策不修复** | 失败不会让数据坏，简化为日志 |
| V7 并发 ingest race condition | ✅ **已决策不修复** | V7 是 CLI-driven，无并发场景 |
| Reconciliation decision log 增长无界 | 第四批监控 + 归档策略 |  |
| Canonical_id UUID 不可读 | 用 `c_<16hex>` 短格式；page frontmatter 加 canonical_id_ref |  |
| Stage 7 forward recovery 不能保证 index 与 page 同步 | index 是派生物，可 rebuild |  |
| SlugAliasRegistry 与 Reconciliation 双系统冲突 | ✅ **已整改** | F15: 选项 A，Reconciliation adapter 调 SlugAliasRegistry |

### Rollback:

- 每个 sub-stage 单独 commit，单独可回滚
- Stage 1-2 改动若破坏现有测试，立即 revert
- Stage 5 整改保留旧 `fill_slots` 为 legacy adapter；新代码走 `fill_slots_v2`
- Stage 6R 是新增模块（旧 `extract_relations` 不动），可独立废弃
- Stage 7 manifest 持久化路径 `.index/commits/`；新项目无旧 checkpoint
- Reconciliation 是完全独立模块（`src/reconciliation/`），不动 source-local pages，最安全

---

## 7. Completion evidence

### 预计 commit 序列（每个 Task 一个 logical commit）

```
feat(stage1): add failed/uncertain/traits/fingerprint to Classification
fix(stage1): remove incomplete from valid doc types
feat(stage1): route Stage 1 failure to review queue
feat(stage2): add SegmentationResult + 5 invariants
fix(stage2): remove Stage 1 doc_type hard gate
feat(stage2): add author byline deterministic splitter
feat(stage2): unify UTF-8 byte offset coordinate system
feat(stage3): add CompletenessResult + 3 failure classes
feat(stage3): bounded evidence pack + Stage 2 consumption
fix(stage3): checkpoint double-key (proven_incomplete only skip)
feat(stage4): add ClusterResult + 8 metrics + 3 failure classes
feat(stage4): TopicCandidate multi-knowledge support
feat(stage4): two-stage LLM discovery + grouping
feat(stage4): script-generated topic_id (cut LLM title dependency)
fix(stage4): __other__ → unresolved signal
feat(stage5): Claim/EvidenceRef + canonical spans
feat(stage5): Stage 5A evidence extraction (先证据后 claim)
feat(stage5): 10 mechanical claim invariants
feat(stage5): semantic reviewer for high-risk claims
feat(stage5): Stage 5B deterministic page synthesis + FillResult
feat(stage7): CommitManifest + crash consistency
feat(stage7): page frontmatter ownership + revision_hash
feat(stage7): durable failure fact + queue projection fallback
feat(stage7): source checkpoint pipeline_fingerprint double-key
feat(stage6r): RelationPredicate ontology + RelationKey
feat(stage6r): RelationStore independent checkpoint
feat(stage6r): candidate retrieval 6 strategies
feat(stage6r): 12 mechanical invariants
feat(reconciliation): Canonical models + Decision enum
feat(reconciliation): candidate retrieval
feat(reconciliation): identity resolver (LLM only decision)
feat(reconciliation): canonical registry + reversible membership
feat(reconciliation): CLI + Phase 1 minimum closed loop
test(e2e): fault injection covering 6 crash points
docs: update v7-ingestion-pipeline.md + ADR 0011 + ADR 0012
```

### Tests:

- 第一批完成后：现有 `tests/test_v7*` 298 passed + 1 skipped 全绿
- 新增测试覆盖 8 个 stage 的所有整改点（≥ 60 条新测试）
- E2E fault injection 测试（Task 32）

### Static checks:

- `grep -rn 'doc_type == "collection"' scripts/extract_pilot.py` 返回 0（Task 4 验证）
- `grep -rn 'DocType.INCOMPLETE' src/` 返回 0（Task 1 验证）
- `grep -rn '"incomplete"' src/pipeline/v7_extract/doc_classifier.py` 返回 0（Task 1 验证）
- `python -m src.cli classify test.md --dry-run` 不再返回 `incomplete`

### Documentation updated:

- `docs/guides/v7-ingestion-pipeline.md`（Task 33）
- `docs/adr/0011-v7-ingestion-outcome-control-plane.md`（Task 33）
- `docs/adr/0012-v7-knowledge-reconciliation-plane.md`（Task 33，新建）

### Progress ledger updated: yes

- 更新 `.superpowers/sdd/progress.md`
- 第一批 33 个 task 完成后更新 ledger 一次
- 后续批次每个 task 完成后更新一次

---

## 8. Plan 状态转换记录

| 状态 | 时间 | 触发 |
|---|---|---|
| planned | 2026-09-17 | 本 plan 创建 |
| audit-r1 | 2026-09-17 | plan-audit Round 1 完成（17 个问题）|
| audit-r1-reassess | 2026-09-17 | Round 1 重新评估（用户决策：不考虑成本、不管旧 wiki）|
| audit-r1-fix | 2026-09-17 | Round 1 整改 inline（6 个必修 + 4 个建议修）|
| audit-r1-review | 2026-09-17 | Round 1 复审通过 |
| audit-r2 | 2026-09-17 | Round 2 压力测试完成（10 个失败路径）|
| audit-r2-reassess | 2026-09-17 | Round 2 多角度重新评估（4 必修 + 1 回退 / 3 不修）|
| audit-r2-fix | 2026-09-17 | Round 2 极简整改 inline（F8 回退 + FP2/FP3/FP6-minimal/FP10）|
| human-reviewed | 2026-09-17 | 人工 review 通过 |
| **approved** | **2026-09-17** | **全部审查通过** |
| **contract-frozen** | **2026-09-17** | **Contract Freeze 生效**（详见 [contract-freeze](./2026-09-17-v7-remediation-contract-freeze.md)）|
| **in-progress** | **2026-09-17** | ponytail full 启用，Task 1 开始执行 |
| completed | (待触发) | 第一批 33 个 task 全部完成且测试通过 |

### 8.1 执行记录（2026-09-17，subagent-driven-development）

> **本节取代各 Task 小节末尾的 `**Status**: pending` 字段** —— 那些字段是本 plan 起草时的占位，未随执行逐条回填。以本节为准。

**已完成：16 / 33**（Stage 1–4 全部 + Stage 5 前三项）

| Task | Commit | 主题 |
|---|---|---|
| 1 | `73f90988` | Stage 1 `Classification` v4 契约（`failed`/`error`/`uncertain`/`traits`/`evidence_summary`/`classifier_fingerprint`）|
| 2 | `4b4f45bb` | Stage 1 技术失败 → `FAILED`（不再伪装 `INCOMPLETE`）|
| 3 | `8b129fc6` | Stage 2 `SegmentationResult` + `CanonicalItem` + 5 条 invariant |
| 4 | `29012b81` | Stage 2 移除 `doc_type == "collection"` 硬门 + 作者署名切分器 |
| 5 | `8a303beb` | byte/char 坐标分离（`slice_bytes`/`slice_text`）|
| 6 | `613cdde4` | Stage 3 `CompletenessResult \| None` + `TECHNICAL_FAILURE` 分离 |
| 7 | `9201be5f` | Stage 3 bounded evidence pack（HEAD/TAIL/3×MID）+ 消费 Stage 2 |
| 8 | `a84e1c11` | checkpoint 双键（仅 `INCOMPLETE` + fingerprint 匹配才 skip）|
| 9 | `0d439e00` | Stage 4 `ClusterResult` + 9 metrics + 质量门 |
| 10 | `97bf2683` | `TopicCandidate` + 解除 single-topic-per-item |
| 11 | `8a07151e` | 两阶段 LLM（discovery + grouping）+ `TopicDescriptor` |
| 12 | `c053ea41` | 脚本生成 `topic_id`/`page_id` |
| 13 | `848b9b31` | `__other__` 保留 + `unresolved` 信号；修 `_collect_unresolved` 语义 bug |
| 14 | `35f6c2ca` | `Claim`/`EvidenceRef` + `CanonicalSpan`（source-absolute 坐标）|
| 15 | `1db31b3e` | Stage 5A claim extraction（LLM 只回 `span_ids`）|
| 16 | `b9b45c28` | 10 条 mechanical claim invariant + substantive-claim filter |

**当前验收基线**（v7-extract 批次，15 文件）：`3 failed, 223 passed`。

3 个红灯是**过时的 Plan 5 测试**（`test_cluster_version_bumped_to_1_1`、`test_cluster_collection_splitting_rule_in_prompt`、`test_cluster_topic_signature_accepts_doc_type_kwarg`）——它们断言「仅当 `doc_type == collection` 才拆分」，而这正是 **Task 11 移除**的行为。修它等于把已移除的硬门控加回 prompt，属独立决策，**留待人工裁定**（删除/改写这 3 个测试，或补 `cluster.toml` v1.1）。

**待续：17 / 33**（Task 17–33）

- Stage 5 剩余：17（semantic reviewer）、18（Stage 5B deterministic synthesis + `FillResult`）
- Stage 7：19（`CommitManifest` + crash consistency）、20（frontmatter ownership）、21（durable failure fact）、22（source checkpoint fingerprint 双键）
- Stage 6R：23（`RelationPredicate` ontology）、24（`RelationStore`）、25（candidate retrieval）、26（12 条 invariant）
- Reconciliation：27–31（Phase 1 闭环）
- 32（E2E fault injection）、33（文档 + ADR 0012）

---

## 9. Contract Freeze（编码前最后一道门）

**实施前必须先冻结 4 个核心 Contract**——见独立文件：[2026-09-17-v7-remediation-contract-freeze.md](./2026-09-17-v7-remediation-contract-freeze.md)

| Contract | 核心规则 |
|---|---|
| Failure Contract | technical failure 不得映射成 insufficient / unresolved / conflicting |
| Canonical Identity Contract | 仅 SAME / ALIAS / CONFLICT 共享 canonical；其他保持独立 |
| Bounded Evidence Contract | 所有声称 bounded 的 LLM path 必须真 bounded（尤其 Stage 2）|
| Persistence Contract | revision_hash / page-set / pipeline_fingerprint 唯一语义冻结 |

**任何 Task 实施代码不遵守 Contract Freeze → 视为 bug，立即 reject。**

---

**本 plan 已 approved + contract-frozen，可进入编码阶段。**

按 `dev-relay` 规则，编码阶段须切换到 ponytail full（关闭 mattpocock 系），并遵守：

1. 模块边界不可破坏（仅通过 `api.ts` 对外暴露）
2. 禁止为简化实现制造模块耦合
3. 禁止删除必要类型定义、参数校验、异常处理
4. 必要时添加 `ponytail:` 注释标记技术债务
5. 禁止使用 `ponytail ultra`