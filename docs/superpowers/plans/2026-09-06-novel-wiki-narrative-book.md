# novel-wiki 叙事化写作方法论书籍实施计划（历史基线）

> **已被替代：** 当前目标采用 `docs/superpowers/plans/2026-09-06-novel-wiki-book-series-target.md` 的“三本主教程 + 参考库”结构；本文件仅保留单书叙事编译的历史任务拆分。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏现有规则版的前提下，把 `novel-wiki` 编译为可追溯的叙事化写作方法论教程，并先以单章样例作为人工验收入口。

**Architecture:** 保留 `rule_only` 作为默认路径，新增显式 `narrative_draft` / `narrative` 路径。LLM 只处理当前章节的摘要、内容块和关系上下文，输出带 evidence 的结构化章节；编译器把正文、来源索引、章节关系和质量报告一起写入 staged release，只有质量门通过且显式 `--apply` 才更新 `CURRENT.json`。

**Tech Stack:** Python 3.11+、现有 `LLMProvider.complete`、MiniMax OpenAI-compatible Provider、JSON、Markdown、pytest、现有 WebUI 原生 JavaScript/CSS。

**Spec:** `docs/superpowers/specs/2026-09-06-novel-wiki-narrative-book-design.md`

## Global Constraints

- 默认模式保持 `rule_only`；正文外发必须同时显式启用 `--narrative --use-llm --polish` 和项目授权文件。`--narrative` 不带 `--apply` 只生成 `narrative_draft` dry-run；只有 `--narrative --apply` 才能发布 `narrative`。
- LLM 输出必须是结构化 JSON；事实段落必须绑定现有 block/page evidence，不能创建新的 Wiki 事实、页面或关系。
- 任何章节失败、来源覆盖不足、关系 unresolved 超阈值或质量门失败都不得更新 `CURRENT.json`。
- 来源、关系、模型、提示词版本和哈希写入 manifest；API key 不得写入日志或产物。
- 外发前只允许发送项目根目录 allowlist 内的相对来源路径；命中敏感字段时脱敏或拒绝外发。
- 来源覆盖率按全 release 的 eligible page_id 计算；artifact hashes 排除 manifest 自身，manifest 使用独立 canonical digest。
- WebUI 修改 `web/js/views/*.js` 时同步更新 `docs/webui-buttons.md`。
- 每项代码任务先写失败测试，再实现最小改动，再运行定向测试并提交一个逻辑 commit。

---

### Task 1: 固化目标书型与样章 fixtures

**Files:**
- Create: `tests/fixtures/book_narrative/chapter_materials.json`
- Create: `tests/fixtures/book_narrative/rubric.yaml`
- Test: `tests/test_kc/test_book_narrative_contract.py`

**Interfaces:**
- Consumes: existing `PageRecord`, `WikiSnapshot`, outline-v1.
- Produces: deterministic fixture containing one volume, one chapter, two source pages, one cross-chapter relation, one missing-source page, and one illustrative narrative bridge. Missing-source variant is a rejection case; a passing fixture is supplied separately in the same test.

- [ ] **Step 1: Write failing contract tests** for required chapter fields, evidence kinds, source coverage and relation categories.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_narrative_contract.py -q`; expected failure because the narrative contract is absent.
- [ ] **Step 3: Add** the fixture JSON/YAML with exact stable IDs and the five reader tasks: identify method, trace source, distinguish example from fact, follow next chapter, complete exercise.
- [ ] **Step 4: Run** the same test and require PASS.
- [ ] **Step 5: Commit** `test(book): 固化叙事书籍契约与样章夹具`.

### Task 2: Rebuild the writing-domain outline

**Files:**
- Modify: `src/kc/views/book/wiki/theme_outline.py`
- Modify: `src/kc/views/book/wiki/outline_validate.py`
- Test: `tests/test_kc/test_book_narrative_outline.py`

**Interfaces:**
- Consumes: `purpose.md`, theme, page summaries.
- Produces: outline-v1 with five writing-workflow volumes; each chapter has `reader_promise`, `content_roles`, and stable `chapter_id`.

- [ ] **Step 1: Add failing tests** rejecting infrastructure-only volume titles for a writing-domain target and accepting the five workflow volume IDs.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_narrative_outline.py -q`; expected failure.
- [ ] **Step 3: Implement** role validation and prompt fields; preserve old outline-v1 fields and allow legacy rule outlines to load.
- [ ] **Step 4: Run** the test plus `tests/test_kc/test_book_wiki_outline_validate.py`.
- [ ] **Step 5: Commit** `feat(book): 按写作流程生成叙事卷章纲`.

### Task 3: Add evidence-bound narrative output types

**Files:**
- Modify: `src/kc/views/book/wiki/polish_llm.py`
- Modify: `src/kc/views/book/wiki/polish_validate.py`
- Modify: `src/kc/views/book/wiki/model.py`
- Test: `tests/test_kc/test_book_narrative_polish.py`

**Interfaces:**
- Consumes: `ChapterDraft`, `PageRecord`, provider.
- Produces: `NarrativeChapter` with `chapter_id`, `sections`, `exercise`, `source_page_ids`, `chapter_relations`, `polished`, and `failure_reason`.

- [ ] **Step 1: Write failing tests** for valid JSON, unknown evidence rejection, chapter ID mismatch, truncated response, missing exercise, and illustrative bridge labeling.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_narrative_polish.py -q`; expected failure.
- [ ] **Step 3: Implement** the JSON prompt and parser. Require `kind` in `narrative_bridge`, `fact_explanation`, or `exercise`; require evidence for fact/exercise sections; reject absolute paths and sensitive fields before provider call; retry once with the same request hash, then return fail-closed result.
- [ ] **Step 4: Run** focused tests and existing `tests/test_kc/test_book_wiki_polish.py`.
- [ ] **Step 5: Commit** `feat(book): 增加证据绑定的叙事正文契约`.

### Task 4: Propagate source provenance and chapter relations

**Files:**
- Modify: `src/kc/views/book/wiki/aggregator.py`
- Modify: `src/kc/views/book/wiki/reading_aids.py`
- Modify: `src/kc/views/book/wiki/compiler.py`
- Test: `tests/test_kc/test_book_narrative_provenance.py`

**Interfaces:**
- Consumes: `WikiSnapshot`, validated outline, `PageRecord.sources`, `PageRecord.relation_targets`.
- Produces: `chapter_sources`, `unattributed_page_ids`, `chapter_relations`, `source_coverage`, `relation_stats`.

- [ ] **Step 1: Write failing tests** for same-chapter relations, previous/next edges, unresolved targets, namespace edges, and missing sources.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_kc/test_book_narrative_provenance.py -q`; expected failure.
- [ ] **Step 3: Implement** one deterministic assignment map from page ID to chapter ID; resolve targets using the existing normalized/compact/alias logic; exclude only declared namespace relation types from unresolved content metrics.
- [ ] **Step 4: Run** provenance tests and existing relation regression tests.
- [ ] **Step 5: Commit** `feat(book): 补齐来源追溯和章节关系`.

### Task 5: Integrate narrative compilation and staged publication

**Files:**
- Modify: `src/kc/views/book/wiki/compiler.py`
- Modify: `src/cli.py`
- Modify: `src/cli_ext/book_cmd.py`
- Test: `tests/test_kc/test_book_narrative_e2e.py`
- Test: `tests/test_cli_ext/test_book_narrative_cli.py`

**Interfaces:**
- Consumes: validated outline, `NarrativeChapter`, provenance report, quality settings.
- Produces: `reading_experience_mode=narrative`, `body_generation_mode=llm_narrative`, narrative Markdown, `source_index.json`, `chapter_relations.json`, manifest hashes.

- [ ] **Step 1: Add failing E2E tests** asserting default rule build is unchanged, narrative dry-run does not publish, and narrative apply keeps the old pointer when one chapter fails.
- [ ] **Step 2: Run** the two focused test files; expected failure because flags and manifest fields are absent.
- [ ] **Step 3: Add** `--narrative` as an explicit alias requiring `--use-llm --polish`; pass provider and policy through existing preflight; compile all chapters through the evidence-bound renderer; refuse mixed narrative/rule chapters on apply.
- [ ] **Step 4: Add** quality checks: full-release page-level source coverage ≥ 0.95 (eligible page_id denominator), unresolved content relation ratio ≤ 0.05 (namespace edges excluded), all chapters have exercises, all evidence IDs exist, all non-manifest output files hashed and manifest canonical digest verified.
- [ ] **Step 5: Run** focused E2E plus existing V3/V4 compiler tests.
- [ ] **Step 6: Commit** `feat(book): 接入叙事模式并保持原子发布`.

### Task 6: Update Book WebUI for reader-facing metadata

**Files:**
- Modify: `src/services/files.py`
- Modify: `src/server/routes/files.py`
- Modify: `web/js/views/book.js`
- Modify: `web/style.css`
- Modify: `web/index.html`
- Modify: `docs/webui-buttons.md`
- Test: `tests/test_server/test_service_files.py`

**Interfaces:**
- Consumes: narrative release manifest, `source_index.json`, `chapter_relations.json`.
- Produces: API fields for mode, volume/chapter labels, source coverage, previous/next/related chapters, and exercise state.

- [ ] **Step 1: Add failing service/API tests** for narrative manifest fields, selected-version content, missing-source display, and relation links.
- [ ] **Step 2: Run** `PYTHONPATH=. pytest tests/test_server/test_service_files.py -q`; expected failure for the new fields.
- [ ] **Step 3: Implement** integrity-verified reads for the new sidecar files; keep legacy releases readable with explicit fallback labels.
- [ ] **Step 4: Render** narrative volume headings, source/relationship sidebar, and a visible “示范场景” marker; keep the current version dropdown.
- [ ] **Step 5: Update** `docs/webui-buttons.md`, bump static asset query versions, run Node syntax check and API smoke test.
- [ ] **Step 6: Commit** `feat(webui): 展示叙事正文来源和章节关系`.

### Task 7: Generate and review one real MiniMax chapter

**Files:**
- Create: `docs/reports/2026-09-06-book-narrative-sample.md`
- Modify: `knowledge/novel-wiki/.llm-wiki/policy.json` only after explicit content-export authorization is present.

**Interfaces:**
- Consumes: one selected chapter, its source pages, configured MiniMax Provider.
- Produces: local sample release/report; never updates `CURRENT.json`.

- [ ] **Step 1: Run** narrative preflight with one chapter and verify policy, provider, input size, allowlisted relative source paths, sensitive-field scan and output directory.
- [ ] **Step 2: Call** MiniMax once with the structured prompt; retry at most once on transient failure.
- [ ] **Step 3: Validate** evidence, source coverage, chapter relations, word count and exercise checks.
- [ ] **Step 4: Write** the sample to a separate report/staging directory and expose its exact metadata.
- [ ] **Step 5: Manually review** title alignment, narrative continuity, factual traceability and reader usefulness before any full-book apply.
- [ ] **Step 6: Commit** the sample only if it is explicitly labeled sample-only.

### Task 8: Full-book pilot, acceptance and rollback rehearsal

**Files:**
- Modify: `docs/superpowers/plans/2026-09-06-novel-wiki-narrative-book.md`
- Test: `tests/test_kc/test_book_narrative_e2e.py`
- Create: `docs/reports/2026-09-06-book-narrative-acceptance.md`

**Interfaces:**
- Consumes: approved sample style, full Wiki snapshot, narrative compiler.
- Produces: dry-run report, quality metrics, release candidate, rollback evidence.

- [ ] **Step 1: Run** a 3–5 chapter pilot; record input pages, token usage, latency, provider errors, source coverage and relation resolution.
- [ ] **Step 2: Run** all five reader tasks plus the V3/V4 regression suite; fail if any hard gate is below threshold.
- [ ] **Step 3: Run** full dry-run without changing `CURRENT.json`; inspect the outline for title/topic mismatch and mixed content types.
- [ ] **Step 4: Publish** only after manual acceptance of the pilot; verify the old release remains selectable.
- [ ] **Step 5: Rehearse** a corrupted chapter file and a provider failure; verify pointer remains on the prior release.
- [ ] **Step 6: Commit** `test(book): 完成叙事书籍验收和回滚演练`.

## Completion Criteria

- The design sample passes manual review and is labeled sample-only.
- Default `rule_only` builds and existing releases remain readable.
- Narrative release meets all eight publication gates in the design spec.
- WebUI displays real volume/chapter names, source coverage, chapter relationships, and the narrative mode.
- A provider failure, invalid evidence, missing source, unresolved relation over threshold, or corrupted output leaves `CURRENT.json` unchanged.
- Full-book implementation is not declared complete until the 3–5 chapter pilot and full dry-run evidence are attached to `docs/reports/2026-09-06-book-narrative-acceptance.md`.
