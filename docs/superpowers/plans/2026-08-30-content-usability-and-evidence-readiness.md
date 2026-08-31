# Content Usability and Evidence Readiness Implementation Plan

> **Execution status (2026-08-31):** Tasks 0–8 implemented and evidenced. Task 9 validation completed with the official `graphify update . --no-cluster` structural mode; see `docs/reports/2026-08-30-content-readiness-acceptance.md` for the exact gate results and the four preserved GLM5.2 truncation failures.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Subagents are not permitted for this repository delivery; execution stays in the main session.

**Goal:** 在所有摄取入口建立可重算、可审计、不会制造幻觉知识的内容可用性与证据就绪门禁。

**Architecture:** Collector 先生成不可变 `ExtractionArtifact`，再由无 LLM 的 policy/profile evaluator 产生 `ContentAssessment`。共享 readiness gate 在 Analyzer 前统一拦截 candidate、legacy、HTTP 和 programmatic 入口；可用内容进入现有 Analyzer → Reviewer → Promoter → Generator → Writer，其他状态进入 specialist、quarantine 或 source inventory。证据始终绑定 canonical block，不从 prompt 文本重新搜索。

**Tech Stack:** Python 3.11+, frozen dataclasses, JSON-compatible policy serialization, existing `CanonicalDocument`, pytest, existing HTTP/queue/wiki storage, graphify for repository structure validation.

**Spec:** `docs/superpowers/specs/2026-08-30-text-preprocessing-design.md`

## Global Constraints

- 原始字节是 provenance 根；不得修改、复制、清理或覆盖 `knowledge/novel-wiki`。
- 不使用 fuzzy matching、语义猜测、LLM 自评或 provider 专属特判修复证据。
- 不使用一个全局“少于 N 字拒绝”规则；阈值只能属于明确的 `format × extraction_method × content_kind` profile。
- Analyzer 只能引用本次 registry 中的 `source_id + block_id + verbatim quote`。
- canonical 文本是唯一证据基准；prompt view 不得成为证据替代品。
- `ready_with_warning` 可以进入 Analyzer，但不得降低 Reviewer 的 fail-closed 规则。
- `skip_no_content`、`quarantine_degraded`、`unsupported` 不得创建或发布 `KnowledgeObject`。
- `route_specialist` 必须有确定的 route、最大尝试次数和失败终态，不能无限重试或退回通用 Analyzer。
- 历史 `legacy-sanitizer-v0` bundle/evidence 只读兼容；新 policy 不静默重写旧记录。
- 不新增 provider，不修改 MiniMax 配额或用户级 provider 配置。
- 所有报告、失败原因、provider cause chain 和 chunk 状态必须保留；`skip_no_content` 不计为 provider failure。

## Current baseline and explicit gap

已有实现包括文本 canonical/prompt 分层、`source_id + block_id + quote` 严格绑定、基础 `ContentAssessment`、Analyzer 前文本 gate、pilot 审计字段和配置路径容错。它已经覆盖 Markdown/文本的主要问题，但不能被误称为完整跨格式子系统。

当前 rejected 分支仍可能写入带警告的 source page；这只能作为历史兼容行为，Task 4 完成后新 gate 的 `skip_no_content` 只能写 inventory/quarantine record，不得把它作为知识 source page 发布。

本计划剩余交付必须补齐：

1. `ExtractionArtifact` 与来源范围合同；
2. 可校验、可序列化、可版本回滚的 policy/profile registry；
3. format/extraction/content-kind 的确定性选择与 mixed 聚合；
4. specialist、legacy 和所有入口的 gate 封闭；
5. 统一 quarantine/inventory/audit schema；
6. 全量 staging inventory、新 policy 下的 15 样本 pilot 和量化验收。

## Canonical data contracts

以下类型是跨模块合同。字段名、枚举值和序列化键固定；后续任务不得使用同义字段替代。

```python
@dataclass(frozen=True)
class SourceRange:
    unit: str                 # line | paragraph | page | table_row | image_region
    start: int                # inclusive, 0-based within unit
    end: int                  # exclusive
    unit_index: int           # page/row/paragraph index

@dataclass(frozen=True)
class ExtractionArtifact:
    source_id: str
    source_bytes_sha256: str | None
    input_text: str
    input_text_sha256: str
    format: str               # md | txt | pdf | docx | xlsx | html | image
    extraction_method: str     # native_text | pdf_text | docx_text | xlsx_cells | html_text | ocr
    extractor_version: str
    ranges: tuple[SourceRange, ...]
    extraction_errors: tuple[str, ...]

@dataclass(frozen=True)
class EvidenceCapacity:
    blocks: int
    chars: int
    units: int
    min_span_chars: int
    max_span_chars: int

@dataclass(frozen=True)
class ContentAssessment:
    assessment_version: str
    policy_version: str
    source_id: str
    format: str
    extraction_method: str
    content_kind: str         # prose | title_definition | table | list | code | image_ocr | mixed | unknown
    decision: str             # ready | ready_with_warning | route_specialist | skip_no_content | quarantine_degraded | unsupported
    reason_codes: tuple[str, ...]
    evidence_capacity: EvidenceCapacity
    analyzer_called: bool
    provenance_complete: bool
    metadata_ratio: float
    repetition_ratio: float
    replacement_ratio: float
    nonempty_units: int
    failure_reason: str | None
```

The neighboring return types are also fixed:

```python
@dataclass(frozen=True)
class ReadinessPolicy:
    policy_version: str
    profiles: tuple[ContentProfile, ...]

@dataclass(frozen=True)
class ReadinessResult:
    artifact: ExtractionArtifact
    assessment: ContentAssessment
    route: str | None

class PipelineDisposition(StrEnum):
    CONTINUE = "continue"
    SPECIALIST = "specialist"
    AUDIT_ONLY = "audit_only"

@dataclass(frozen=True)
class ReplayResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    failure_reason: str | None
```

`ContentKind`, `ContentProfile`, `NoiseReport` and `RuleApplication` remain the stable types from the text-preprocessing design; Task 1 extends `ContentProfile` with the format and extraction dimensions listed below.

The closed reason-code set is `empty_input`, `metadata_only`, `duplicated_navigation`, `no_evidence_capacity`, `legitimate_short`, `high_repetition`, `encoding_degraded`, `ocr_degraded`, `missing_provenance`, `unsupported_format`, `oversized_block`, `empty_subblock`, `specialist_failed`, and `policy_violation`. A route is stored separately from `specialist_failed`; reason codes are never dynamically invented from source names.

`content_kind` 不允许使用 `metadata_only`；元数据页表示为 `content_kind=prose` 加 `reason_codes` 中的 `metadata_only`。统一 JSON 键使用 `decision`，不再同时出现 `readiness_decision`。hash、规则命中和 block registry 保存在同一 ingest audit record，不复制成第二套含义不同的字段。

### Decision semantics

每个 artifact 先得到 block-level assessment，再按以下优先级聚合：

1. `quarantine_degraded`：存在不可接受的编码/提取退化，且无法证明范围可靠；
2. `unsupported`：没有可用 profile 或提取格式不受支持；
3. `route_specialist`：已有专用 route，但当前文本不足以安全分析；
4. `ready` / `ready_with_warning`：至少一个可引用 block，且没有阻断性退化；
5. `skip_no_content`：所有 block 均无 evidence capacity。

`mixed` 文档只汇总可引用 block；空子块不抹掉有效子块，但必须保留 `empty_subblock` warning。所有 block 都不可引用时才是 `skip_no_content`。

### Deterministic metrics and v1 profile matrix

所有指标在 canonical block units 上计算，并在 `ContentAssessment` 中保留分母：

- `evidence_capacity.chars = sum(len(block.content) for evidence-capable blocks)`；结构噪声删除只影响 prompt view，不改变 canonical evidence capacity。
- `metadata_ratio = metadata_unit_chars / nonempty_unit_chars`；空白单位不进入分母。
- `repetition_ratio = repeated_nonempty_units / nonempty_units`；重复判断先移除零宽字符并做 NFC，不做语义相似度判断。
- `replacement_ratio = replacement_char_count / max(len(input_text), 1)`。
- `provenance_complete` 只有在每个 evidence-capable block 恰好有一个有效 `SourceRange` 时为 true。

v1 profile key 必须是三元组；未命中不得回退到 prose：

| format | extraction_method | content_kind | minimum rule | short rule | blocking signals |
|---|---|---|---|---|---|
| md/txt | native_text | prose | at least 1 unit and 20 chars | 2 chars, non-metadata, `ready_with_warning` | zero capacity; metadata-dominant repeated residue |
| md/txt/html | native_text/html_text | title_definition | heading/label plus one definition unit | 2 chars with `:`/`：`/`=` or heading structure | missing structure and no capacity |
| md/txt/html | native_text/html_text | list | 2 list items | 1 non-empty item with valid list marker | malformed or empty items |
| md/txt/html | native_text/html_text | code | 1 fenced or indented code unit | 1 code unit | no code unit |
| pdf/docx | pdf_text/docx_text | prose | 1 mapped unit and 20 chars | 2 mapped chars with complete range | extraction error or missing range |
| xlsx/pdf | xlsx_cells/pdf_text | table | 1 complete row with at least 2 cells | 1 complete row | missing columns or no mapped row |
| image/pdf | ocr | image_ocr | mapped text plus valid image region | 2 mapped chars with confidence metadata | replacement ratio > 0.30 or missing region |

`minimum_chars` 只参与 profile 内部判定；它不能单独触发拒绝。`short rule` 和 evidence capacity 必须同时满足。`unknown` 没有 profile，直接 `unsupported` 或进入已命名 specialist。

## Implementation tasks

### Task 0: Freeze baseline, schema vocabulary, and golden fixtures

**Files:**

- Modify: `docs/superpowers/specs/2026-08-30-text-preprocessing-design.md`
- Create: `tests/fixtures/content_readiness/golden.json`
- Create: `tests/fixtures/content_readiness/README.md`
- Test: `tests/test_pipeline/test_content_readiness_contract.py`

**Interfaces:**

- Produces the frozen reason-code list, decision list, audit JSON shape and fixture labels used by Tasks 1–8.
- Fixture labels are `empty`, `metadata_only`, `duplicated_navigation`, `short_prose`, `short_definition`, `real_prose`, `repeated_real_prose`, `garbled`, `table`, `list`, `code`, `ocr_degraded`, `mixed`, `unsupported`.

- [ ] Step 1: Write a contract test asserting every fixture has `source_id`, expected `content_kind`, expected `decision`, and a deterministic expected reason-code set.
- [ ] Step 2: Run `pytest tests/test_pipeline/test_content_readiness_contract.py -v`; expected result is RED because the frozen contract and fixture manifest do not exist.
- [ ] Step 3: Add the manifest and update the text-preprocessing design with the exact contracts in this plan; do not add source-specific exceptions.
- [ ] Step 4: Run the contract test and verify GREEN; reject unknown reason codes and inconsistent enum values.
- [ ] Step 5: Commit with `docs(kc): freeze content readiness contract`.

**Acceptance:** No `metadata_only` content kind, no `readiness_decision` alias, no unlabelled fixture, and no requirement that depends on a source filename.

### Task 1: Implement versioned policy/profile registry

**Files:**

- Create: `src/pipeline/text_preprocessing/policy.py`
- Modify: `src/pipeline/text_preprocessing/types.py`
- Modify: `src/pipeline/text_preprocessing/__init__.py`
- Test: `tests/test_pipeline/test_content_readiness_policy.py`

**Interfaces:**

```python
def load_policy(policy_version: str = "content-policy-v1") -> ReadinessPolicy: ...
def select_profile(policy: ReadinessPolicy, *, format: str, extraction_method: str, content_kind: ContentKind) -> ContentProfile | None: ...
def serialize_policy(policy: ReadinessPolicy) -> dict: ...
```

`ReadinessPolicy` contains an immutable profile tuple and a policy version. Each profile contains `format`, `extraction_method`, `content_kind`, `minimum_units`, `minimum_chars`, `short_minimum_chars`, `short_requires_structure`, `metadata_dominance_ratio`, and `repetition_warning_ratio`.

- [ ] Step 1: Write RED tests for duplicate profile keys, negative thresholds, `short_minimum_chars > minimum_chars`, missing policy version, unknown content kind, and deterministic serialization.
- [ ] Step 2: Run the policy test file and record the expected validation failures.
- [ ] Step 3: Implement the frozen dataclasses and strict registry validation; keep built-in v1 profiles in code so unreadable user configuration cannot silently alter policy.
- [ ] Step 4: Run policy tests and compare `serialize_policy(load_policy())` twice; both outputs must be byte-equivalent.
- [ ] Step 5: Commit with `feat(kc): add versioned readiness policy registry`.

**Acceptance:** Profile selection is explicit and deterministic; no fallback from an unknown format to prose; policy version is present in every assessment.

### Task 2: Introduce ExtractionArtifact and provenance ranges

**Files:**

- Modify: `src/pipeline/collector.py`
- Modify: `src/utils/extract/pdf.py`
- Modify: `src/utils/extract/office.py`
- Modify: `src/utils/extract/html.py`
- Create: `src/pipeline/extraction_types.py`
- Test: `tests/test_pipeline/test_extraction_artifact.py`

**Interfaces:**

```python
def collect_artifact(file_path: Path, *, source_id: str) -> ExtractionArtifact: ...
def validate_artifact_ranges(artifact: ExtractionArtifact) -> None: ...
```

Native Markdown/TXT ranges are line-based; PDF ranges are page/text offsets; XLSX ranges are sheet/row units; DOCX ranges are paragraph units; OCR ranges are image regions. If an extractor cannot map output to a source range, it records an extraction error and the artifact cannot supply evidence.

- [ ] Step 1: Add fixture tests for Markdown/TXT, PDF, DOCX, XLSX, HTML and OCR-shaped artifacts; assert bytes hash is never replaced by decoded text hash.
- [ ] Step 2: Run the fixture tests and verify RED for missing artifact/range APIs.
- [ ] Step 3: Implement adapters using existing extractors; preserve original text and attach extractor/version metadata.
- [ ] Step 4: Run the fixture tests and assert every evidence-capable block has exactly one valid range; unmappable derived text fails closed.
- [ ] Step 5: Commit with `feat(kc): add extraction artifact provenance`.

**Acceptance:** A Reviewer/replay caller can trace every accepted canonical block to a source range without reading extractor internals.

### Task 3: Implement deterministic content assessment

**Files:**

- Modify: `src/pipeline/text_preprocessing/api.py`
- Modify: `src/pipeline/text_preprocessing/readiness.py`
- Modify: `src/pipeline/text_preprocessing/types.py`
- Test: `tests/test_pipeline/test_content_readiness.py`

**Interfaces:**

```python
def assess_artifact(artifact: ExtractionArtifact, *, policy_version: str = "content-policy-v1") -> ContentAssessment: ...
def assess_blocks(artifact: ExtractionArtifact, *, policy_version: str = "content-policy-v1") -> tuple[ContentAssessment, ...]: ...
```

Rules:

- `content_kind` comes from deterministic extractor/structure metadata; if absent, it is `unknown`, never LLM-inferred.
- A short input is accepted when it has non-metadata evidence capacity and meets the selected profile’s short-unit rule; it receives `legitimate_short` and never becomes an automatic rejection solely because of character count.
- `metadata_only` requires zero evidence capacity, or metadata-dominant repeated navigation/title residue under the selected profile.
- Repetition is a warning for legitimate prose and a blocking signal only when combined with metadata dominance; table/list/code profiles do not use prose repetition rules.
- `replacement_ratio` or missing provenance can produce `quarantine_degraded`; unknown format produces `unsupported`.

- [ ] Step 1: Add golden tests for all Task 0 labels, including two-character Chinese prose, duplicated title residue, valid repeated prose, and mixed valid/empty blocks.
- [ ] Step 2: Run the tests and verify RED for missing artifact/profile integration.
- [ ] Step 3: Implement assessment from artifact metadata and selected profile; use only deterministic metrics.
- [ ] Step 4: Run golden tests twice in separate processes and compare serialized assessments.
- [ ] Step 5: Commit with `feat(kc): implement deterministic content assessment`.

**Acceptance:** The same artifact/policy produces the same serialized assessment; metadata-only and legitimate-short are distinct; false acceptance of all negative golden fixtures is zero.

### Task 4: Close the Analyzer gate across every entry point

**Files:**

- Modify: `src/pipeline/ingest.py`
- Modify: `src/pipeline/stages/analyzer.py`
- Modify: `src/pipeline/triage.py`
- Modify: `src/pipeline/ingest_report.py`
- Modify: `src/server/routes/ingest.py`
- Test: `tests/test_pipeline/test_readiness_gate.py`
- Test: `tests/test_server/test_ingest_readiness.py`

**Interfaces:**

```python
def apply_readiness_gate(artifact: ExtractionArtifact) -> ReadinessResult: ...
async def route_after_readiness(
    result: ReadinessResult,
    *,
    provider: object,
    paths: WikiPaths,
    task_id: str,
) -> PipelineDisposition: ...
```

The shared gate runs before both candidate and legacy Analyzer paths. HTTP enqueue, queue worker, `run_ingest`, `generate_ingest`, and direct programmatic calls use the same gate. `analyzer_called` is set only at the actual Analyzer invocation boundary.

Disposition rules:

- `ready` and `ready_with_warning`: continue to the selected pipeline.
- `route_specialist`: enqueue one named specialist attempt and re-assess its returned artifact.
- `skip_no_content`: write inventory/quarantine audit only; no `KnowledgeObject`, no source knowledge page, no Writer publication.
- `quarantine_degraded` and `unsupported`: write quarantine record with `failure_reason`; no Analyzer call.

- [ ] Step 1: Write tests with a provider that fails the test if called for each blocking decision, plus tests proving both candidate and legacy modes use the gate.
- [ ] Step 2: Run gate tests and verify RED for bypass or missing disposition handling.
- [ ] Step 3: Implement the shared gate and disposition writer; preserve retries and cause chains without classifying skips as provider failures.
- [ ] Step 4: Run gate tests, HTTP tests, and existing pipeline tests.
- [ ] Step 5: Commit with `feat(kc): enforce readiness gate across ingest paths`.

**Acceptance:** No blocking decision reaches Analyzer; no skipped source is promoted or published; all entry points produce the same decision for the same artifact.

### Task 5: Seal evidence contract, chunking, and replay

**Files:**

- Modify: `src/pipeline/analyzer.py`
- Modify: `src/kc/mainline.py`
- Modify: `src/kc/compiler/evidence.py`
- Modify: `src/pipeline/ingest.py`
- Modify: `scripts/kc_novel_wiki_pilot.py`
- Create: `scripts/kc_readiness_replay.py`
- Test: `tests/test_kc/test_evidence_readiness_replay.py`

**Interfaces:**

```python
def replay_evidence(record: dict, artifact: ExtractionArtifact) -> ReplayResult: ...
def serialize_audit(assessment: ContentAssessment, report: NoiseReport, *, analyzer_called: bool, failure_reason: str | None) -> dict: ...
```

The audit schema is fixed as:

```json
{
  "assessment_version": "content-readiness-v1",
  "policy_version": "content-policy-v1",
  "source_id": "raw/sources/example.md",
  "format": "md",
  "extraction_method": "native_text",
  "content_kind": "prose",
  "decision": "ready",
  "reason_codes": [],
  "analyzer_called": true,
  "evidence_capacity": {"blocks": 1, "chars": 120, "units": 4, "min_span_chars": 2, "max_span_chars": 80},
  "failure_reason": null,
  "preprocessing_version": "text-preprocess-v1",
  "source_bytes_sha256": "...",
  "input_text_sha256": "...",
  "canonical_text_sha256": "...",
  "prompt_text_sha256": "...",
  "evidence": []
}
```

- [ ] Step 1: Add replay tests for wrong source, wrong block, hidden block, rewritten quote, cross-block quote, hash mismatch, and accepted exact quote.
- [ ] Step 2: Run replay tests and verify RED for every missing rejection path.
- [ ] Step 3: Implement audit serialization and replay against canonical ranges; never search other blocks after explicit block declaration fails.
- [ ] Step 4: Run replay tests and assert `false_accepts == 0` across all negative fixtures.
- [ ] Step 5: Commit with `fix(kc): make readiness evidence replayable`.

**Acceptance:** Every accepted evidence record replays exactly; every negative evidence case remains rejected with a reason code and original cause chain.

### Task 6: Implement specialist routes and mixed-format aggregation

**Files:**

- Create: `src/pipeline/specialists/__init__.py`
- Create: `src/pipeline/specialists/ocr.py`
- Create: `src/pipeline/specialists/table.py`
- Modify: `src/pipeline/ingest.py`
- Test: `tests/test_pipeline/test_specialist_routes.py`

**Interfaces:**

```python
async def run_specialist(route: str, artifact: ExtractionArtifact) -> ExtractionArtifact: ...
```

Route contracts:

- `ocr`: returns text plus image-region ranges and OCR replacement/confidence metrics;
- `table`: returns row/cell units with sheet/page ranges and column completeness;
- `image`: returns image-region units or a deterministic unsupported result;
- one specialist attempt per source/method; failure becomes `quarantine_degraded` with `specialist_failed`, while the failed route is stored in the separate `route` field.

`unknown` never falls through to prose. A mixed artifact keeps block-level provenance and aggregates only evidence-capable blocks.

- [ ] Step 1: Add fake specialist fixtures and tests for success, missing ranges, empty output, timeout, and second-attempt prohibition.
- [ ] Step 2: Run the tests and verify RED for route and aggregation contracts.
- [ ] Step 3: Implement the minimal adapters around existing extraction capabilities; do not add a provider.
- [ ] Step 4: Run specialist tests and format-specific pipeline tests.
- [ ] Step 5: Commit with `feat(kc): add bounded specialist readiness routes`.

**Acceptance:** No OCR/table/unknown artifact reaches generic Analyzer without a valid specialist result and a fresh assessment.

### Task 7: Make audit, quarantine, security, and rollback durable

**Files:**

- Create: `src/pipeline/readiness_audit.py`
- Modify: `src/pipeline/ingest_report.py`
- Modify: `src/services/quality.py`
- Modify: `src/cli.py`
- Test: `tests/test_pipeline/test_readiness_audit.py`
- Test: `tests/test_cli_ext/test_readiness_cmd.py`

**Interfaces:**

```python
def write_readiness_record(root: Path, record: dict) -> Path: ...
def read_readiness_record(path: Path) -> dict: ...
def compare_readiness_records(old: dict, new: dict) -> dict: ...
```

Records go under `.index/quarantine/readiness/<source-key>.json`; by default they contain hashes, source key, metrics, decision, reason and failure chain, not a duplicate full source body. The CLI exposes read-only inventory and record comparison plus an explicit policy-version selection for replay. Any policy-version change creates a new report and never overwrites the prior one.

Operational rules:

- API keys and provider headers are excluded from records and logs;
- record writes are atomic and permission failures are reported, not silently discarded;
- a corrupt record is an audit error and never treated as an accepted assessment;
- rollback selects a previously installed policy version for new reads/replays; it does not rewrite historical records;
- old `legacy-sanitizer-v0` records are read-only and retain their original hashes/block IDs.

- [ ] Step 1: Write tests for atomic write, corrupt record, permission failure, no-source-body default, version comparison, and legacy read-only behavior.
- [ ] Step 2: Run audit tests and verify RED for persistence and rollback behavior.
- [ ] Step 3: Implement the record store and CLI read-only commands; keep source inventory distinct from knowledge pages.
- [ ] Step 4: Run audit, CLI and server tests.
- [ ] Step 5: Commit with `feat(kc): persist readiness audit and rollback records`.

**Acceptance:** Every skip/reject/specialist failure is queryable, versioned, non-sensitive by default, and distinguishable from provider failure.

### Task 8: Run full staging inventory and stratified 15-sample pilot

**Files:**

- Modify: `scripts/kc_novel_wiki_preflight.py`
- Modify: `scripts/kc_novel_wiki_pilot.py`
- Create: `scripts/kc_novel_wiki_inventory.py`
- Create: `docs/reports/2026-08-30-content-readiness-inventory.md`
- Test: `tests/test_kc/test_novel_wiki_inventory.py`

**Interfaces:**

```python
def inventory(project: Path, *, output: Path, policy_version: str) -> dict: ...
def select_stratified_sources(inventory: dict, *, limit: int = 15, seed: int = 20260830) -> list[str]: ...
```

Workflow:

1. Preflight validates that project, output and protected original roots are disjoint.
2. Inventory reads clean staging only, calls no provider, and writes one record per source with hashes, format, extraction method, decision, reasons and evidence capacity.
3. Human labels the fixed 15 pilot sources by inventory class before provider execution; selection is stratified, not smallest-file-size-only.
4. Pilot reports `accepted`, `skipped`, `rejected`, `needs_human_review`, and `provider_error` separately.
5. Accepted evidence is replayed; skipped/rejected records are checked for `analyzer_called=false`.

- [x] Step 1: Write tests for protected-root overlap, full-source coverage, deterministic stratified selection, category accounting, and no-provider inventory.
- [x] Step 2: Run inventory tests and verify RED for the new report contract.
- [x] Step 3: Implement read-only inventory and update pilot selection/audit propagation.
- [x] Step 4: Run the full clean-staging inventory, then the stratified 15-sample pilot without touching original `knowledge/novel-wiki`.
- [x] Step 5: Run replay and record counts, failure classes, and provider cost; commit reports and scripts separately from source data.

**Acceptance:** Inventory covers every staging source exactly once; the 15-sample report is generated under the current policy; accepted evidence replay is 100%; negative golden evidence has `false_accepts=0`; skipped sources have no Analyzer call.

### Task 9: Final verification and release gate

**Files:**

- Modify: `.superpowers/sdd/progress.md`
- Modify: this plan
- Create: `docs/reports/2026-08-30-content-readiness-acceptance.md`

**Release criteria:**

- Frozen golden set: zero false accepts; zero false rejects for `short_prose` and `short_definition`; each supported profile has at least one passing and one blocking fixture.
- Full staging inventory: `selected == unique_sources`, every record has a decision, and protected-root check passes.
- Stratified pilot: exactly 15 sources, categories reported separately, no unclassified failure, and all accepted evidence replayed.
- Gate coverage: candidate, legacy, HTTP, queue and programmatic paths all prove `analyzer_called=false` for blocking decisions.
- Provenance: every accepted block has a valid source range and stable source/block IDs; hashes are recomputable.
- Operations: corrupt/inaccessible config, audit store, template and registry paths produce bounded errors or safe read-only fallback; no secret appears in audit output.
- Rollback: an older policy can re-read/replay records without mutating historical hashes or source data.
- Regression: `tests/test_pipeline`, `tests/test_kc`, `tests/test_server`, targeted inventory/replay tests, `compileall`, `git diff --check` on changed files, and `graphify update .` pass.

- [x] Step 1: Run the complete validation matrix and capture exact command/output in the acceptance report.
- [x] Step 2: Run protected-root and working-tree checks; restore only test-generated artifacts if a test wrote them.
- [x] Step 3: Update the progress ledger and mark only evidenced tasks complete.
- [x] Step 4: Commit the acceptance report and final plan status; do not push.

## Risk register and controls

| Risk | Failure condition | Control / evidence |
|---|---|---|
| False accept | navigation or OCR garbage reaches Analyzer | negative golden fixtures, metadata-dominance rule, `false_accepts=0` |
| False reject | short title/definition or valid short prose is skipped | dedicated short fixtures, zero short-content false rejects |
| Format drift | extractor output loses source location | `ExtractionArtifact` range validation and extractor version |
| Policy drift | new policy changes old conclusions silently | immutable policy version, comparison report, no overwrite |
| Route bypass | legacy/HTTP path skips gate | entry-point matrix with provider-call sentinel |
| Specialist loop | OCR/table failure retries forever | one attempt, typed failure disposition, audit record |
| Data exposure | quarantine copies raw sensitive content | hash/metadata-only records and secret redaction test |
| Resource exhaustion | huge blocks or OCR jobs consume unbounded resources | block limits, timeout, one specialist attempt, no partial publication |
| Source mutation | test or pipeline writes original knowledge tree | preflight disjoint-root check and final protected-root diff check |

## Migration and rollback

1. Existing `text-preprocess-v1` records remain readable.
2. Existing `legacy-sanitizer-v0` records are never rewritten in place.
3. New records use `content-readiness-v1` and `content-policy-v1`.
4. Policy changes create a new policy version and a new report directory.
5. Replays use the record’s declared preprocessing/policy version; an unavailable version is an audit error, not an automatic fallback.
6. Rollback changes the selected policy for new evaluations only; it cannot turn a failed historical evidence record into an accepted one.

## Audit status after整改

- First-principles review: addressed by separating artifact, assessment, preprocessing, evidence binding and publication responsibilities.
- Risk review: addressed in Tasks 6–9 with specialist bounds, audit persistence, secret exclusion, resource limits and rollback evidence.
- Reverse challenge review: addressed by fixing enum/field contradictions, defining mixed aggregation, closing legacy/unknown routes and making short-content semantics explicit.
- Final acceptance review: blocked until Task 8 produces the full inventory and current-policy 15-sample report; old pilot numbers are not final evidence for this revised plan.

## Completion evidence

- Final plan revision: this document, revised after four independent role reviews.
- Implementation commits already present: `242adc45`, `5ca5560e`.
- Current text/KC/server regression baseline is recorded in `.superpowers/sdd/progress.md`.
- Remaining completion evidence is generated only by Tasks 0–9; no claim of full cross-format completion is valid before the release criteria pass.
