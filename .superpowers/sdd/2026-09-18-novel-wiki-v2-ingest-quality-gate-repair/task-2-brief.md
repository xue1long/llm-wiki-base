# Task 2 brief — enforce resolved templates and fail-closed slots

Read the plan at `docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair.md` and Task 1 tests/report before coding. Implement only Task 2 after Task 1 is complete.

## Scope

Allowed production files:

- `src/pipeline/generator.py`
- `src/pipeline/ingest.py`

Allowed tests:

- Task 1 tests
- `tests/test_wiki/test_templates_renderer.py`
- existing generator/ingest tests needed for the behavior

## Required behavior

1. Candidate generation renders through the resolved project template for every page type; old fixed headings cannot be final output.
2. Required slot handling is slot-level, not a body-string guess. Use verdicts `FILLED`, `DECLARATIVE_ABSENCE`, `EMPTY`, `PLACEHOLDER` or the smallest equivalent existing mechanism.
3. Do not alter the renderer's existing unit-test behavior; prevent invalid placeholder pages at the formal ingest/write boundary.
4. A validated candidate whose downstream concept fails slot/structure checks may produce source-only plus warning/review. Analyzer parse failure, source mismatch, reviewer rejection, or promoter failure remains failed/quarantined, not source-only.
5. Keep LLM processing-depth schema at `concept|memory|operation`; source/stub are system-produced page depths.

## Constraints

- Reuse existing renderer, slot status and atomic writer mechanisms.
- Do not invent a new planner or new dependency.
- Preserve legacy path behavior unless the current candidate path specifically needs the fix.
- Run focused tests and write `.superpowers/sdd/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair/task-2-report.md`.
- Do not spawn subagents.
