# SDD ledger — plan: docs/superpowers/plans/2026-09-08-unified-book-llm-pipeline.md

## Preflight

- Base commit: `c7f96c94a3a0c66c2cea790fef5ca48017e65c68`
- Existing worktree: heavily dirty; preserve all unrelated and pre-existing Book changes.
- Plan scope: only `book build-from-wiki`; do not change legacy `book build`.
- Parallelization ruling: the user explicitly requested parallel subagents; use disjoint write sets and integrate only after each result is independently reviewed.

## Task boundary scan

| Task | Write set | Shared interface | Ruling |
|---|---|---|---|
| Rules | `src/kc/views/book/wiki/rules.py`, rule tests | Produces immutable rules snapshot/hash | Can run parallel; no compiler/CLI edits. |
| CLI modes | `src/cli.py`, `src/cli_ext/book_cmd.py`, CLI tests | Produces plan/preview/apply mode mapping | Can run parallel; compiler integration remains a later merge point. |
| Prompt boundary | `src/kc/views/book/wiki/polish_llm.py`, polish tests | Consumes rules snapshot | Can run parallel; do not edit compiler/preflight. |
| Compiler gates | `src/kc/views/book/wiki/compiler.py`, quality/compiler tests | Consumes mode and rules snapshot; owns publish gate | Can run parallel only with disjoint files; integration may need follow-up. |
| Project bootstrap/docs | `src/cli_ext/project_cmd.py`, ADR/docs | Produces template and durable contract | Can run parallel; no runtime compiler edits. |

## Decisions

- Ruling: treat the existing dirty Book implementation as the integration baseline; do not reset or overwrite it.
- Ruling: `--plan`, `--preview`, and `--apply` are the public mode names; rule-only remains diagnostic compatibility only.

## Progress

- Task 1: implemented and reviewed PASS.
- Task 2: implemented; review finding fixed by executing the validate hook in focused tests.
- Task 3: implemented; focused tests passed; one legacy budget test exposed a contract mismatch.
- Task 4: implemented, including rules-loader integration; focused tests passed.
- Task 5: implemented and reviewed PASS with a minor test-strength note.
- Focused verification: 24 passed.
- Broader affected suite: 55 passed, 13 failed because legacy tests lack `book.rules.md` or expect rule-only apply; test migration is in progress.
- Expanded affected suite after focused test migration: 61 passed.
- Full `tests/test_kc` regression: 776 passed, 17 legacy-contract failures remain; these are isolated to missing fixture rules or old direct rule-only publish assertions and are assigned to a test-only migration agent.
- CLI help smoke check: `--plan`, `--preview`, and `--apply` are exposed and mutually exclusive.
- Final focused verification after fixture migration: 61 passed.
- Remediation: plan mode now stages outline/metadata only (`generation_mode=plan`, no chapter Markdown); preview/apply remain the only body-generating modes.
- Remediation: release acceptance evidence is staged before `CURRENT.json` switching; acceptance-write failure is fail-closed and tested.
- Remediation: manifest and acceptance evidence record `rules_path` in addition to the rules hash/snapshot; five reusable rule fixtures added.
- Regression verification: `tests/test_kc` 795 passed; CLI Book suites 43 passed; acceptance-write atomicity test passed.
- Full-repository run was stopped after a slow unrelated broad pass; `--maxfail=1` exposed one legacy novel-wiki fixture missing `book.rules.md`, which was migrated, but the 540-page suite was not rerun to completion.
