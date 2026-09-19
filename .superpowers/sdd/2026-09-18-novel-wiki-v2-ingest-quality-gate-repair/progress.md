# SDD ledger — plan: docs/superpowers/plans/2026-09-18-novel-wiki-v2-ingest-quality-gate-repair.md

## Preflight conflict scan

| Task | Shared file/interface | Conflict check | Ruling |
|---|---|---|---|
| 1 ↔ 2 | `tests/test_pipeline/test_ingest_generate_commit_split.py`, generator output contract | Task 1 fixes the expected contract; Task 2 implements template/fail-closed behavior | Task 1 tests may initially fail; Task 2 owns implementation |
| 1 ↔ 3 | generator tests and semantic page disposition | Task 1 owns gold assertions; Task 3 owns prompt/variant disposition | Variant response must be review/quarantine, not silently merged |
| 2 ↔ 3 | `src/pipeline/generator.py` | Both touch candidate rendering; prompt changes must preserve slot verdict and renderer boundary | Execute sequentially; Task 3 cannot bypass Task 2 slot checks |
| 2 ↔ 4 | `src/pipeline/ingest.py`, processing depth and template contract | Task 2 owns pre-write slot verdict; Task 4 owns shared enum/target validation | Page type + depth predicate is the shared contract |
| 2 ↔ 5 | ingest source-only and publication state | Task 2 decides which pages survive; Task 5 decides KC/Wiki/Vector/Book state | Final manifest page_ids must be based on post-gate pages |
| 3 ↔ 4 | taxonomy relations and unresolved references | Task 3 constrains output; Task 4 canonicalizes/validates all targets | Taxonomy is virtual; canonical stored form is `taxonomy-<slug>` |
| 4 ↔ 5 | reconcile results and publication/gap state | Task 4 produces classified gaps; Task 5 persists state and retries | No unresolved target may be silently discarded |
| 5 ↔ 6 | final smoke expectations | Task 5 provides deterministic tests; Task 6 runs isolated real flow | Smoke is last and never mutates the original raw source |

## Plan rulings

- Ruling: execute in the current worktree because the user explicitly requested implementation in this shared project; preserve unrelated changes and never use broad staging/cleanup.
- Ruling: “清理之前的数据” means generated artifacts of the single-document test only; preserve `raw/`, `.wiki-templates/`, `schema.md`, `purpose.md`, `.llm-wiki/project.json`, and project identity.
- Ruling: taxonomy keeps the existing persisted `taxonomy-<slug>` form for backward compatibility; `taxonomy/<name>` is normalized at input boundaries.
- Ruling: `source` remains a deterministic source-page depth but is not added to the LLM response enum; page type + depth is validated jointly.
- Ruling: semantic title variants are never fuzzy-auto-merged; exact duplicates/registered aliases may canonicalize, otherwise the variant is quarantined for review.

## Task status

- Task 1: complete (tests/fixture added; committed as `72ec2caf`; focused contract now green)
- Task 2: complete (initial commit `e8bf9431`, review fixes `940ba7f9`; 129 focused tests passed)
- Task 3: complete (commit `679a2772`; semantic constraints and variant tests passed)
- Task 4: complete (local implementation; 67 focused tests passed; no subagent available after user switched to main session)
- Task 5: complete (local implementation; 72 focused tests passed; staged bundles excluded from Book)
- Task 6: todo
