# Task 1 brief — lock the representative ingestion contract

Read the plan at `docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair.md` first, but only implement Task 1.

## Scope

Add regression tests using existing fake providers/fixtures. Do not change production code in this task.

Files allowed:

- `tests/test_pipeline/test_ingest_generate_commit_split.py`
- `tests/test_pipeline/test_generator.py`
- `tests/test_pipeline/test_quality_gate.py`
- optionally `tests/fixtures/novel_wiki_v2_outline_source.md` if existing fixtures cannot express the source

## Required assertions

1. The representative outline source contract is one deterministic source page plus two concepts: `大纲写作技巧` and `大纲四要素`.
2. `提纲的重要性` is not an independent page; `小说大纲写作技巧` is not silently written as a variant page.
3. Concept output follows the project v3.0.0 resolved template and contains no system placeholder.
4. A downstream concept with invalid/missing required content can be dropped while a valid source page remains, with a warning/review result.
5. The concept facts cover time/place/characters/main content and the blueprint/direction purpose.
6. Evidence/source references are preserved; missing author/platform/URL/example must not be invented.
7. A bad generated semantic variant must lead to `NEEDS_HUMAN_REVIEW`/quarantine, never silent full success.

## Rules

- Use existing test helpers and fake providers; no network/real LLM.
- Keep the tests focused on the boundary between generated pages and writer/gate.
- Run the narrow pytest command from the plan.
- Write a report to this same directory as `task-1-report.md` with files changed and test output.
- Do not spawn subagents.
