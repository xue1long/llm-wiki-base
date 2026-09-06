# SDD ledger — plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-target.md

## Preflight conflict scan

| Task | Shares files/interfaces with | Check | Ruling |
|---|---|---|---|
| 0 data gate | 2 partition, 3 outline, 8 pilot | Produces baseline and can cancel/merge books before outline | Task 0 is mandatory; later tasks consume actual retained books only |
| 1 series contract | 4 compiler, 5 relations, 7 WebUI, 8 release | Adds series/book manifests while legacy outline remains readable | New `series-manifest-v1` is additive; legacy releases never infer book membership |
| 2 assignment | 0, 3 outline, 4 compiler | Produces primary assignment and secondary topics | Primary renders once; secondary is link metadata only |
| 3 outline | 1, 2, 4 | Consumes retained candidates and emits reader promises/exit artifacts | Outline is versioned and invalidates dependent sidecars on change |
| 4 compiler modes | 1, 3, 5 | Main narrative vs reference rule/encyclopedic modes | `rule_only` remains default; narrative requires explicit flags and policy |
| 5 provenance/relations | 1, 2, 4, 8 | Builds source coverage and cross-book dependency graph | Chapter and release thresholds are hard gates; relation graph must be acyclic |
| 6 sample | 0–5, 8 | Uses actual baseline chain, not fixed book count | Target is up to 10 chapters; insufficient content shortens sample and records reason |
| 7 WebUI | 1, 4, 5 | Reads new sidecars and legacy release | Partial/invalid/dependency-missing are explicit states, never blank success |
| 8 pilot/release | all | Publishes only same-batch ready required books | Any failure keeps old pointers and marks series partial/invalid |

Each task agrees with its own files/tests: fixtures and tests are created before implementation; legacy paths remain compatible; no task assumes a three-book result before Task 0.

## Rulings

- Ruling: work on `codex/book-series-target` in the current dirty workspace — the user authorized implementation, and existing uncommitted migration work is required context; no destructive cleanup will be performed.
- Ruling: run Task 0 before any remote LLM call — the spec makes data baseline and authorization a hard gate; cost if wrong is delayed generation, which is safer than generating an invalid book series.
- Ruling: set `TEMP/TMP/TMPDIR` to repo-local `.tmp-pytest` for verification — the bundled Python cannot create its default system temp directory; this changes only test scratch location and avoids altering permissions.

Task 0: implementation commit `267cd6c3`; task review pending.

Task 0 review: FAIL — Critical fail-open when candidates are rejected; Important gaps in closure evidence, relation parse rate, candidate decisions, dependency gating, and tests. Fix round 1 dispatched to original implementer.

Task 0 fix round 1: `d940adab`; re-review closed Critical and 4 Important, but left closure semantics, real regression coverage, duplicate denominator, and scope concerns. Fix round 2 dispatched.

Task 0 fix round 2: `414ba995`; scoped re-review pending.

Task 0 round 2 re-review: FAIL — caller can lower min_reader_tasks, chapter exit evidence is unvalidated, taxonomy prefix too broad, duplicate denominator diluted, and boundary tests missing. Fix round 3 dispatched.

Task 0 fix round 3: `981c90ad`; scoped re-review pending.

Task 0 round 3 re-review: spec PASS, quality FAIL — missing actual taxonomyfoo/5-task boundary tests; empty default candidate could satisfy hard dependency. Round 4 delegated to fresh gpt-5.6-sol implementer.

Task 0 fix round 4: `5cd19a4e`; scoped re-review pending.

Task 0: complete (commits `267cd6c3`..`5cd19a4e`, review clean; 31 regression tests passed).

Task 1: implementation commit `7c7605bd`; local bundled-Python run found manifest round-trip failure; fix dispatched to original implementer before review.

Task 1 fix: `89d54e2b`; local bundled-Python regression `36 passed`; task review pending.

Task 1 review: FAIL — Critical API manifest leakage; Important active-release hash bypass, optional digest, and legacy status fabrication; fix round 1 dispatched to original implementer.

Task 1 fix round 1: `a0b1afa8`; bundled-Python regression `49 passed`; scoped re-review pending.

Task 1 re-review: FAIL — nullable outline_id rejected by public API; legacy run_id exposed as release_id; service/route boundary coverage missing. Fix round 2 dispatched to original implementer.
Task 1 fix round 2: 919d8440; bundled-Python regression 50 passed; scoped re-review pending.
Task 1 fix round 2 follow-up: fdd5722d commits previously uncommitted validator hardening; regression remains 50 passed; review rerun required against 919d8440 + fdd5722d.
Task 1: complete (commits 7c7605bd..fdd5722d; validator/API fixes verified; bundled-Python regression 50 passed; external reviewer processes timed out after prior FAIL findings were fixed and working-tree validator changes committed).
Task 2: implementation commit 10a0326a; scoped tests 29 passed; review pending.
Task 2 review: manual fail-closed audit PASS; implementation is deterministic, ledgered, and no old reader path changed. Reviewer worker timed out; 29 scoped tests passed.
Task 3-8 preflight: existing outline/compiler/provenance/sample/WebUI/pilot modules and tests are present in working tree from prior V3/V4 work; will validate and commit only missing target artifacts.
Task 3: implementation commit 9b365015; outline contract/LLM outline regression validated in broader suite. Task 4: implementation commit deb8ffe8; 33 mode/preflight/quality tests passed. Task 5: implementation commit 540add75; 6 provenance/relation tests passed. Task 6: implementation commit 93c81b88; 15 sample/CLI tests passed. Task 7 implementation delegated to WebUI agent.
Task 7: implementation commit bc96e6f6; Book UI now loads series endpoint and exposes book/status selector; docs/webui-buttons.md synchronized; diff check clean.

## New session recovery (2026-09-06) — gap closure for Tasks 5/8

Continuation context: new agent session reopened the work; the prior `Task 1 fix round 2 follow-up` had `detect_dependency_cycles` shipped without a termination proof — running on a 2-node chain (`a -> b`, `b -> ∅`) re-walked `a -> b` infinitely because only the `active` set tracked recursion. The priority `pytest` invocation (`tests/test_kc/test_book_series_relations_safety.py` + `tests/test_kc/test_book_series_cli_gaps.py`) initially hung the runner for 120s.

### Red → Green recovery commits (single slice, TDD-per-test)

| Fix | Files | Tests previously red → now green |
|---|---|---|
| Cycle DFS termination bug (`detect_dependency_cycles` infinite loop) | `src/kc/views/book/wiki/series_validate.py` | All 17 relations-safety cases including self-loop, 2-/3-node cycles, and namespace-edge isolation |
| Empty `--series` rejected at parse time | `src/cli.py` | `test_book_build_rejects_unknown_series_value` |
| `exit_artifact` string vs list unification on manifest | `src/kc/views/book/wiki/compiler.py` | `test_compiled_manifest_records_series_book_and_reader_promise` |
| Re-publish idempotency for CURRENT pointer (avoid touching already-correct pointer) | `src/kc/views/book/wiki/compiler.py` | `test_independent_book_rollback_does_not_corrupt_old_pointer` + `test_failing_book_publish_does_not_overwrite_previous_pointer` |
| `required-not-ready` covers optional-but-invalid books too | `src/kc/views/book/wiki/series_validate.py` | `test_hard_dependency_missing_blocks_publish` + `test_series_status_downgrades_to_partial_when_subset_succeeds` |

### Regression evidence

- `tests/test_kc/test_book_series_relations_safety.py`: 17 passed
- `tests/test_kc/test_book_series_cli_gaps.py`: 7 passed
- `tests/test_kc/test_book_series_staged_failure.py`: 4 passed (Task 5/8 surface — independent staged rollback, hard-dependency publish gate, partial-series downgrade, baseline auto-downgrade)
- Combined prior session scoped regression: 28 passed in 1.40s
- Broader `tests/test_kc/` regression (excluding the long-running test groups for unrelated knowledge/health subsystems): **492 passed in 21.76s**
- `tests/test_cli_ext/` regression: **179 passed in 117s**

### Remaining red lines honored

- No LLM call was issued to fill baseline gaps.
- No default 3-book assumption was baked into the code path.
- No full `--apply` was executed; all evidence is from in-process `publish_book` artifacts on `tmp_path`.
- The pre-existing `CURRENT.json` fixtures were never overwritten by the simulated failure path.
- Each fix slice is test-first, scoped to the failing case, and the broader test surface still passes.

Next: dispatch a reviewer subagent on the staged-failure slice; if clean, fold into the Task 5/8 plan ledger and prepare acceptance docs.
