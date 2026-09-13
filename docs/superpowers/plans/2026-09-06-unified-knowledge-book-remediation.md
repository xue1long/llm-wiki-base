# Minimal Unified Knowledge Book Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为一个知识域生成一本面向人阅读的 canonical Book，教程只作为引用章节和小节的阅读路径，并用真实小规模样例证明正文、来源、发布和回滚闭环成立。

**Architecture:** Wiki 是事实、来源和搜索层；Book 是经过页面裁决、基本去重和 LLM 编辑后的正文层；TutorialPath 是 Book 上的导航覆盖层，不拥有正文。第一版只做 section/page 级来源，不建设 claim 图谱、自动冲突裁决或多 Book 系统。

**Tech Stack:** Python 3.11+、现有 `src/kc/views/book/wiki/` 编译器、JSON manifest、Markdown release、现有 WebUI、pytest；不新增数据库、搜索索引或第三方依赖。

**Spec:** `knowledge/novel-wiki/purpose.md`

**Delivery decision:** 本计划拆成两个交付阶段。阶段 0 只交付持久化编辑输入和 rule-only vertical slice；阶段 0 未通过前，不进入 LLM 正文、TutorialPath UI 或全量构建。

**Implementation status (2026-09-07, personal-reading remediation):** 已补齐统一出版级 LLM 请求计数（提纲、正文、重试共用 `max_llm_calls`，每次请求先占额）、所有外部 LLM 路径的显式授权 `external_llm_allowed`、受限敏感级别前置阻断、来源 allowlist 前置阻断、CURRENT 失败保护，以及确定性的 `release-acceptance.json` 自动验收报告。个人阅读发布只保留真实 Provider 试读和人读验收两个人工门；全库审批不属于本书的发布条件。报告仍单独记录 build outcome、derived freshness、approval pending、manifest/provenance/budget/auth/pointer 检查，并校验 sidecar 与 release manifest 的绑定；Book API 使用同一 freshness 派生函数。仍未完成：`chapter-technique` 的真实 Provider 人读验收；该门未完成前不得宣称 LLM 个人阅读版已发布。

## Global Constraints

- 当前 `novel-wiki` 视为一个知识域，默认只有一本 canonical Book；多知识域 Book 延后，不固化为全局永久限制。
- TutorialPath 只保存章节/小节引用、任务和检查点，不复制章节正文。
- `rule_only` 可以作为正式降级版本；`llm_complete` 才是完整目标版本；`llm_partial` 只能留在 preview/staging；`failed` 不更新 `CURRENT.json`。
- 第一版来源追溯到 section/page 级；claim-level evidence、source fragment 和自动 entailment 检查延后。
- 页面裁决至少支持 `include`、`duplicate`、`conflict`、`exclude`、`unresolved`。
- 正式 Book 输入固定存于 `book-wiki/book.json`、`book-wiki/editorial/curation.json`、`book-wiki/editorial/outline.json` 和 `book-wiki/editorial/paths.json`；不得把策展状态只放在 staging。
- `conflict` 可以进入 Book，但必须以争议状态呈现；未裁决冲突不得被写成单一确定结论。
- section 状态至少支持 `normal`、`disputed`、`blocked`、`editorial`。
- 章节 ID 不由标题直接生成；标题修改不能破坏现有路径。章节拆分/合并第一版要求人工重建路径，不建设完整 lineage 服务。
- 编译必须绑定一个 Wiki snapshot；失败不得修改旧 release 或 `CURRENT.json`。
- Book freshness 使用 `fresh`、`stale`、`building`、`failed`；Wiki 更新只会先标记 stale，不自动覆盖当前完整 release。
- 第一版正文策略为 `generated_only`，不提供人工正文覆盖层。
- 全量扩展前必须设置 `max_llm_calls`、`max_input_tokens`、`max_output_tokens`、`max_retries` 和 `max_runtime_seconds`；达到任一上限时生成 `partial`，不得更新 CURRENT。
- Pilot 默认预算固定为：`max_llm_calls=3`、`max_input_tokens=60000`、`max_output_tokens=15000`、`max_retries=1`、`max_runtime_seconds=900`；全量构建必须显式提供更高且经批准的配置，不得沿用 pilot 上限之外的隐式默认值。
- LLM 阶段必须同时具备 `external_authorized`、`budget_cap` 和 `approver`；任一缺失时只允许 rule-only，不允许调用外部 Provider。
- 外部 Provider 调用前必须执行敏感信息、来源授权和路径 allowlist 检查；使用本地 Provider 时仍保留审计记录。
- Book 负责目录阅读，Wiki 负责搜索；不新增第二套搜索系统。

## Minimal Target Model

```text
WikiSnapshot
  -> PageDisposition / BookCuration
  -> BookStructure
  -> ChapterEdition
  -> TutorialPath[]
  -> BookRelease
```

最小对象：

```text
PageDisposition: page_id, disposition, target_chapter_id, reason
Chapter: chapter_id, title, sections[]
Section: section_id, title, body, source_page_ids, status
TutorialPath: path_id, title, steps[], status
BookRelease: release_id, snapshot_id, generation_mode, release_status, book_freshness, wiki_snapshot_hash, editorial_state_hash, release_manifest_hash
```

本文中的简写含义固定为：`llm_complete` = `generation_mode=llm + release_status=complete`；`llm_partial` = `generation_mode=llm + release_status=partial`。

最小持久化 schema：

```json
{
  "book.json": {
    "schema_version": "book-v1",
    "project_id": "novel-wiki",
    "domain_id": "novel-wiki",
    "book_id": "novel-wiki-book",
    "body_policy": "generated_only",
    "editorial_revision": 1,
    "book_freshness": "fresh"
  },
  "editorial/curation.json": {
    "schema_version": "book-curation-v1",
    "domain_id": "novel-wiki",
    "book_id": "novel-wiki-book",
    "editorial_revision": 1,
    "pages": [
      {
        "page_id": "page-001",
        "disposition": "include",
        "primary_chapter_id": "chapter-001",
        "secondary_references": [],
        "reason": "pilot inclusion",
        "content_hash_at_review": "..."
      }
    ]
  },
  "editorial/outline.json": {
    "schema_version": "book-outline-v1",
    "book_id": "novel-wiki-book",
    "editorial_revision": 1,
    "volumes": [{"volume_id": "volume-001", "chapters": []}]
  },
  "editorial/paths.json": {
    "schema_version": "tutorial-path-v1",
    "book_id": "novel-wiki-book",
    "paths": []
  }
}
```

规则：

- 页面只能有一个正文 primary owner；其他章节通过 `secondary_references[]` 引用，不复制正文。
- `source_page_ids` 证明来源范围，不声称已经完成 claim-level 事实证明。
- 过渡句、标题和任务说明可标记为 `editorial` 或 `task`，不得伪造为直接来源。
- 正式发布必须能区分 rule-only、LLM complete、争议内容和失败状态。

## Out of Scope

- 三本独立教程书或多书依赖图。
- TutorialPath 独立正文存储。
- Claim 图谱、段落级证据库、自动事实蕴含检测。
- 自动化冲突裁决；第一版只识别并显式呈现冲突。
- 完整 chapter lineage、自动拆分/合并迁移。
- 全量 Wiki 首次通过作为成功条件。
- 全局图数据库、章节注册中心、第二套搜索索引。
- 复杂人工编辑器；第一版不保存用户直接改写，避免覆盖规则尚未确定。

## File Map

- Modify `src/kc/views/book/wiki/partition.py`: 页面纳入、排除和裁决记录。
- Modify `src/kc/views/book/wiki/aggregator.py`: 按章节聚合页面，保留页面顺序和来源，不承担语义裁决。
- Modify `src/kc/views/book/wiki/compiler.py`: 单 Book 编译、状态、staged release 和 CURRENT 发布。
- Modify `src/kc/views/book/wiki/polish_llm.py`: 生成结构化 section 正文，而不是只生成编排元数据。
- Modify `src/kc/views/book/wiki/polish_validate.py`: 校验结构、来源页面、冲突状态和 Provider 输出。
- Modify `src/kc/views/book/wiki/quality_gate.py`: 增加最小 Book 正文和来源质量门；不实现 claim-level 判定。
- Create `src/kc/views/book/wiki/tutorial_path.py`: 路径引用模型和最小验证。
- Modify `src/services/files.py` and `src/server/routes/files.py`: 在核心闭环通过后暴露 Book/Path 状态。
- Modify `web/js/views/book.js`: 在现有阅读器上增加路径覆盖。
- Modify `docs/webui-buttons.md`: 同步记录 WebUI 变更。
- Create focused tests under `tests/test_kc/` and `tests/test_server/`.
- Create: `book-wiki/book.json`, `book-wiki/editorial/curation.json`, `book-wiki/editorial/outline.json`, and `book-wiki/editorial/paths.json` as the first persistent Book input fixture.

---

### Task 0: Deliver the persistent Book input package

**Files:**
- Create: `docs/superpowers/specs/2026-09-06-unified-knowledge-book.md`
- Test: `tests/test_kc/test_unified_book_contract.py`

**Depends on:** none.

- [ ] **Step 1: Write failing contract tests**

  Verify schema versions, `project_id/domain_id/book_id` mapping, generated-only body policy, one primary chapter owner, secondary references, and `book_freshness` values.

- [ ] **Step 2: Run the focused tests**

  Run: `PYTHONPATH=. pytest tests/test_kc/test_unified_book_contract.py -v`

  Expected: FAIL until the minimal contract is represented.

- [ ] **Step 3: Write the spec**

  Record the model, the four persistent Book input files, release/freshness states, compatibility boundary, section/page provenance scope, generated-only body policy, and the explicit out-of-scope list. Do not add a series-level content container.

- [ ] **Step 4: Create the first persistent input files**

  Create the four files under the Book root using the minimal schemas above. `editorial/curation.json` and `editorial/outline.json` are formal inputs; staging may only contain copies.

- [ ] **Step 5: Define legacy identity mapping**

  New builds use `domain_id/book_id`. Existing `series_id` and legacy `book_id` are read-only compatibility fields. The new compiler must not use `series_id` to decide page ownership. Add a fixture proving an old release is readable without making it a new editorial input.

- [ ] **Step 6: Select the real pilot fixture**

  Select 10–30 real source-backed pages that can form 2–3 Book chapters. This is a Book pilot, not the cancelled three-tutorial gate. Include a duplicate and a conflict when the real data contains them; if no real conflict exists, record that absence instead of fabricating one. Record page IDs, selection reasons, excluded pages and source permissions.

- [ ] **Step 7: Gate**

  If no real pilot can form 2–3 coherent chapters, mark `pilot_blocked` and stop. Do not bypass the current baseline by inventing content. Stage 0 may deliver schemas and a blocked report, but no LLM implementation starts.

### Task 1: Add page disposition and explicit chapter assignment

**Files:**
- Modify: `src/kc/views/book/wiki/partition.py`
- Modify: `src/kc/views/book/wiki/outline_model.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_kc/test_book_curation.py`
- Test: `tests/test_kc/test_book_structure.py`

**Depends on:** Task 0.

- [ ] **Step 1: Write failing curation tests**

  Cover inclusion/exclusion, duplicate, conflict, unresolved, missing source, one primary chapter owner, secondary reference, and title changes that retain `chapter_id`.

- [ ] **Step 2: Run the tests**

  Run: `PYTHONPATH=. pytest tests/test_kc/test_book_curation.py tests/test_kc/test_book_structure.py -v`

- [ ] **Step 3: Implement the smallest disposition ledger**

  Persist `page_id`, `disposition`, `primary_chapter_id`, `secondary_references`, `reason`, and decision source in `book-wiki/editorial/curation.json`. Staging receives a build copy only. Do not create a registry service. A page with no decision cannot silently enter a formal release.

- [ ] **Step 4: Define chapter assignment**

  Use `editorial/outline.json` as the sole chapter assignment input. Deterministic chunking may create a draft outline, but cannot compete with the persisted outline during compilation. Every included page must map to one primary chapter; secondary reuse must be an explicit reference and must not duplicate body blocks.

- [ ] **Step 5: Implement stable IDs without full lineage**

  Preserve IDs from `book-wiki/editorial/outline.json` when available. New chapters receive IDs once and keep them when only titles or ordering change. Split/merge invalidates affected paths and requires manual path repair.

- [ ] **Step 6: Run focused tests**

  Expected: PASS, including an old manifest fixture.

### Task 2: Produce a rule-only Book vertical slice

**Files:**
- Modify: `src/kc/views/book/wiki/aggregator.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Modify: `src/kc/views/book/wiki/quality_gate.py`
- Test: `tests/test_kc/test_book_wiki_rule_only_vertical.py`

**Depends on:** Task 1.

- [ ] **Step 1: Write failing vertical-slice tests**

  Cover 2–3 chapters, section/page source lists, empty chapter blocking, conflict-labelled content, duplicate page exclusion, and directory ordering.

- [ ] **Step 2: Run the tests**

  Run: `PYTHONPATH=. pytest tests/test_kc/test_book_wiki_rule_only_vertical.py -v`

- [ ] **Step 3: Compile the pilot in rule-only mode**

  Keep current block identity and deterministic ordering. Do not claim semantic deduplication where the compiler only aggregates blocks.

- [ ] **Step 4: Add the minimum quality gate**

  Block missing chapter IDs, missing required source lists, unresolved page ownership, invalid secondary references, and conflict content presented without a `disputed` section status. Emit `chapter_body_present`, `section_source_ids_present`, `curation_revision_present`, and `outline_revision_present`. Do not add automatic factual correctness scoring.

- [ ] **Step 5: Perform the first human read**

  Verify that a person can use the directory to find and read all pilot chapters without relying on Wiki search. Record failures before adding LLM generation.

### Task 3: Add LLM section-body generation with page-level provenance

**Files:**
- Modify: `src/kc/views/book/wiki/polish_llm.py`
- Modify: `src/kc/views/book/wiki/polish_validate.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_kc/test_book_wiki_polish.py`
- Test: `tests/test_kc/test_book_chapter_body.py`

**Depends on:** Task 2.

- [ ] **Step 1: Write failing body tests**

  Cover structured sections, body text, `source_page_ids`, duplicate removal at the provided block level, conflict preservation, invalid JSON, truncation, provider outage, and prompt-injection text inside source content.

- [ ] **Step 2: Run the tests**

  Run: `PYTHONPATH=. pytest tests/test_kc/test_book_wiki_polish.py tests/test_kc/test_book_chapter_body.py -v`

- [ ] **Step 3: Change the LLM output contract**

  Return `chapter_id`, ordered sections, `body`, `source_page_ids`, `content_status`, and editorial/task markers. Keep page-level provenance for v1; do not create claim-level evidence objects.

- [ ] **Step 4: Define safe output states**

  Use these states:

  - `rule_only`: formal fallback release is allowed.
  - `llm_complete`: all required LLM chapters pass; formal target release is allowed.
  - `llm_partial`: preview/staging only; cannot update CURRENT.
  - `failed`: no new release pointer.

- [ ] **Step 5: Validate content boundaries**

  Reject missing source page IDs, unsupported output sections, source prompt injection, malformed output, and unlabelled conflict summaries. Editorial transitions may exist, but must be marked editorial rather than pretending to be direct source facts.

- [ ] **Step 6: Record reproducibility metadata**

  Write provider, model, prompt hash, source snapshot ID, `editorial_revision`, `wiki_snapshot_hash`, `editorial_state_hash`, and generation parameters to the release manifest. Keep body policy `generated_only` explicit.

- [ ] **Step 7: Run focused tests and manually read one LLM chapter**

  Expected: the chapter is readable without Wiki search, while the source page set remains visible to the reader or release inspector.

### Task 4: Publish safely and add reference-only TutorialPath

**Files:**
- Modify: `src/kc/views/book/wiki/compiler.py`
- Modify: `src/kc/views/book/wiki/preflight.py`
- Modify: `src/kc/views/book/wiki/quality_gate.py`
- Create: `src/kc/views/book/wiki/tutorial_path.py`
- Test: `tests/test_kc/test_book_wiki_e2e.py`
- Test: `tests/test_kc/test_book_wiki_staged_failure.py`
- Test: `tests/test_kc/test_tutorial_path.py`

**Depends on:** Tasks 1–3.

- [ ] **Step 1: Write failing release tests**

  Cover first build without CURRENT, existing CURRENT, provider failure, invalid chapter, rule-only fallback, LLM partial output, CURRENT atomicity, old release readability, stale staging, concurrent build lock, freshness transitions, and budget exhaustion.

- [ ] **Step 2: Implement the release order**

  Compare the current Wiki snapshot hash with the CURRENT release before building; mark Book `stale` when they differ. Then run snapshot → mark Book `building` → compile → validate → write complete immutable release → verify input/manifest hashes → atomically update CURRENT → mark Book `fresh`. `llm_partial` and `failed` never update CURRENT; a failed build leaves the prior complete release available.

- [ ] **Step 3: Implement minimal TutorialPath**

  A path stores `path_id`, `title`, `goal`, ordered `chapter_id/section_id` references, tasks, checkpoints and status. It does not store chapter body. Missing references make the path invalid without invalidating the Book.

- [ ] **Step 4: Add conditional external-provider preflight**

  Check allowlisted relative paths, sensitive fields, source authorization and provider type before any external call. Record pass/block/override without writing credentials into logs or release files.

- [ ] **Step 5: Run focused and existing Book tests**

  PowerShell run: `$env:PYTHONPATH="."; python -m pytest tests/test_kc -k "book_wiki or tutorial_path" -v`

### Task 5: Add only the required reader UI and complete the pilot

**Files:**
- Modify: `src/services/files.py`
- Modify: `src/server/routes/files.py`
- Modify: `web/js/views/book.js`
- Modify: `docs/webui-buttons.md`
- Create: `docs/reports/2026-09-06-unified-book-pilot.md`
- Test: `tests/test_server/test_kc_book_routes.py`

**Depends on:** Task 4.

- [ ] **Step 1: Add failing API/UI tests**

  Assert that the API returns one Book tree, path metadata, `book_freshness`, generation mode and release status; selecting a path changes navigation order but not chapter body or release ID.

- [ ] **Step 2: Implement the smallest UI change**

  Reuse the current Book reader. Add directory path selection, next-step display, source/status display, and explicit invalid/partial states. Do not add Book search.

- [ ] **Step 3: Run browser/API smoke tests**

  Expected: directory reading works; a broken path does not hide a valid Book; the same chapter body is identical from multiple paths.

- [ ] **Step 4: Run failure drills**

  Test provider unavailable, invalid/truncated output, source update during build, cancelled path, concurrent build, CURRENT write failure, stale Book marking, editorial-state persistence across rebuilds, and token/call/runtime budget exhaustion. Record pointer, freshness, status and old-release behavior.

- [ ] **Step 5: Perform human acceptance**

  The pilot passes only if a person can locate a topic from the directory, read 2–3 chapters, see source coverage, identify a conflict, and complete the path tasks. A failed pilot blocks corpus expansion.

## Acceptance Checklist

- [ ] One knowledge domain resolves to one canonical Book.
- [ ] Every included page has a disposition and one primary chapter owner.
- [ ] Book has stable chapter/section IDs for title/order changes.
- [ ] Chapter body is readable without Wiki search.
- [ ] Every section has page-level source IDs or an explicit blocked/editorial status.
- [ ] Duplicate and conflict cases are distinguishable.
- [ ] Unresolved conflict is never written as a single settled fact.
- [ ] TutorialPath references chapters/sections and never duplicates body text.
- [ ] `rule_only` fallback, `llm_complete`, `llm_partial`, and `failed` behave differently.
- [ ] Provider failure leaves the previous CURRENT and release readable.
- [ ] Legacy release fixture remains readable.
- [ ] External provider preflight records authorization and sensitive-data decisions.
- [ ] Human pilot passes before full-corpus expansion.
- [ ] Curation and outline survive a rebuild and are not stored only in staging.
- [ ] Wiki changes mark the Book stale without invalidating the last complete CURRENT.
- [ ] Release records Wiki, editorial-state, and manifest hashes.
- [ ] Stage 0 persistent input files validate against their schema versions.
- [ ] New builds do not use `series_id` for page ownership.
- [ ] Budget exhaustion produces partial/failed output without changing CURRENT.
- [ ] Missing external authorization, budget cap or approver prevents external LLM calls.

## Deferred Work After Pilot

- Claim-level evidence and automated entailment checking.
- Paragraph/source-fragment hashes.
- Human override layer and edit conflict resolution.
- Automatic chapter split/merge migration.
- Incremental chapter recompilation and cost dashboards.
- Multiple knowledge-domain Books in one project.
- Advanced path recommendation and learning analytics.

## Plan Audit Result

### Mandatory retained

Product boundary, page-to-chapter assignment, minimal disposition ledger, real chapter body generation, page-level provenance, explicit release states, staged publish/rollback, stable IDs, external-provider preflight, reference-only paths, and human pilot.

### Deliberately deferred

Claim graph, full lineage service, automatic conflict adjudication, multi-book architecture, second search index, and full-scale automation.

### Re-entry gate

Implementation may begin only after Task 0 persistent input files, identity mapping, and schema tests pass. LLM implementation may begin only after the rule-only pilot can form 2–3 coherent chapters. Full-corpus expansion is allowed only after Task 5 human acceptance and the budget gate pass. A passing structural test suite without a readable pilot does not count as completion.
