# Task 4 brief — unify target, taxonomy, duplicate-title, and depth rules

Read the main plan and completed Task 1–3 reports before coding. Use Luna for
implementation and review. Work in the current shared tree; preserve unrelated
changes and do not reset or push.

## Scope

Use exactly the Task 4 production/test/document files listed in the main plan.
The shared target classification must be implemented in the existing
`src/wiki/features/target_resolver.py` and reused by H2 checks,
`src/pipeline/reconcile.py`, and `src/wiki/features/batch_gate.py`.

## Required behavior

1. Classify `sources/...`, `concepts/...`, bare ids, aliases, titles,
   ambiguous targets, unresolved targets, and taxonomy targets consistently.
2. Validate taxonomy through the existing registry. Normalize input
   `taxonomy/<name>` to persisted `taxonomy-<slug>`; valid taxonomy is virtual,
   not a normal page or gap; invalid taxonomy is an explicit taxonomy error.
3. Duplicate-title reporting groups by `(page_type, normalized_title)` so
   same-title source/concept pages do not conflict while same-type duplicates
   still do.
4. Reuse one page-type × processing-depth predicate. Keep old page reads
   compatible; do not silently rewrite old invalid values. LLM depths remain
   `concept|memory|operation`; source/stub are deterministic writers.
5. Ordinary unresolved references retain `referenced_by` and raw hint in the
   gap ledger. Do not silently discard them.
6. Fix the documented wikilink syntax and add/adjust the focused tests in the
   plan. Keep the diff minimal and preserve report field names.

## Verification

Run all Task 4 focused tests plus the Task 1/2 regression tests. Write
`task-4-report.md` with commands/results and any compatibility decision. Do
not amend prior commits.
