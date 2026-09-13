# SDD ledger — plan: docs/superpowers/plans/2026-09-09-book-promotion-and-nonblocking-approval.md

## Setup

- Base commit: `1e2c17a1e189cfc274340cc2f188737403de56c2`
- Working tree contains unrelated changes and generated artifacts; preserve them.
- The bundled `sdd-workspace` Bash helper could not start on Windows due to host permission denial. This ledger is the equivalent plan-scoped workspace record.
- No reachable external Spec is named by the plan; the revised plan and current Book implementation are the binding authority.

## Pre-flight conflict scan

| Item | Shared files/interface | Finding | Ruling |
|---|---|---|---|
| Task 0 ↔ Task 1 | `acceptance.py`, release identity | Task 0 defines immutable content identity; Task 1 adds mutable human evidence. | Human/lifecycle evidence stays outside the immutable manifest and is bound to its digest. |
| Task 0 ↔ Task 2 | `compiler.py`, candidate validation/publish | Task 2 must consume the typed candidate protocol from Task 0. | No direct `Path` publication; Task 2 uses `validate_candidate_release` then `publish_validated_candidate`. |
| Task 0 ↔ Task 4 | policy identity, lifecycle metadata | Policy and vector result must not mutate candidate content identity. | Bind policy identity at generation and write vector status as derived result/evidence. |
| Task 1 ↔ Task 2 | acceptance report, human review | Human review is advisory and must not become an Apply-from gate. | Only automated acceptance and governance evidence affect promotion. |
| Task 2 ↔ Task 3 | `compiler.py`, call accounting | Promotion must have zero provider calls; budget estimator applies only to fresh generation. | Keep Apply-from on a provider-free path; do not reuse generation preflight. |
| Task 2 ↔ Task 5 | CURRENT, lifecycle, failure tests | Rollout must exercise the same protocol and failure matrix. | No real provider run until deterministic promotion tests pass. |
| Task 0 | protocol tests vs implementation | Requires immutable manifest, source revision, lifecycle states, project/book isolation. | Implement the smallest typed validator and sidecar state needed for later tasks. |
| Task 1 | report/sidecar tests vs existing hard-coded pending | Existing tests expect `pending`; behavior change requires focused test updates. | Preserve old report loading; emit new advisory fields for new reports. |
| Task 2 | CLI/compiler tests vs current parser/publisher | No `--apply-from` or shared validated publisher exists. | Add parser constraint and refactor one publication seam; no second publisher. |
| Task 3 | estimator tests vs current call-sites | Existing runtime accounting uses `pending`; new metadata must be backward-readable. | Introduce one estimator and transitional decoder; do not change retry policy beyond scope. |
| Task 4 | policy/vector docs vs runtime | Existing policy loading and vector commands already exist in separate layers. | Extend result/reporting only; no secrets in policy and no Book-triggered vector writes. |
| Task 5 | full verification vs real content | Real MiniMax content is out of scope for deterministic tests. | Use provider-free fixtures; real preview requires explicit separate authorization. |

## Rulings

- Ruling: preserve all unrelated dirty files and generated Book artifacts — they predate this execution and are outside the plan.
- Ruling: normal Apply and Apply-from must converge on one validated publication primitive — two publication implementations would invalidate the core safety goal.
- Ruling: no real MiniMax call during implementation — the user authorized prior runs, not an implicit new spend for tests.

## Task status

- Task 0: complete — local implementation; 10 focused tests passed; no provider calls
- Task 1: complete — local implementation; 7 focused tests passed; no provider calls
- Task 2: complete — local implementation; promotion/CLI/regression tests passed; no provider calls
- Task 3: complete — local implementation; 22 budget/body tests passed; no provider calls in preflight cases
- Task 4: complete — local implementation; vector separation and CLI regressions passed
- Task 5: complete — full deterministic Book/CLI regression 836 passed; provider-free promotion drill passed; no real provider call
