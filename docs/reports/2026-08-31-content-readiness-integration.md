# Content-readiness safe integration audit

Date: 2026-08-31

## Refs

- Main baseline: `1c472d7fb56c021a88328e6a241ada940a83da28`
- Delivery ref: `8c7f7209515cd798a2f4da9e73101f751b3c68bf`
- Merge base: `e75e840ea3f43a65e9b1fa1006f1ebc59c60d745`
- Integration branch: `codex/content-readiness-integration`

## Integration method

The delivery history was not merged wholesale because it diverged from main
with unrelated history. The integration branch started at main and received
two semantic content-readiness commits plus one small regression-fix commit.
Conflicts were resolved by preserving both required behaviors (for example,
pilot and readiness audit metadata), not by selecting one side wholesale.

The integration worktree uses sparse checkout exclusions for:

- `knowledge/`
- `raw/`
- `.index/`

This kept protected user data out of the working tree. No source data was
copied, rewritten, cleaned, or deleted.

## Scope

Included: canonical text preprocessing, deterministic content readiness,
strict `source_id`/`block_id`/quote evidence binding, replayable evidence
audits, specialist routing, inventory/pilot tooling, and their tests/docs.

Excluded: providers, MiniMax configuration, user knowledge data, raw source
data, vector/index data, and unrelated pre-existing worktree changes.

## Verification

- `tests/test_pipeline tests/test_kc tests/test_server`: **1283 passed, 7 skipped, 41 warnings**.
- Ingest and publication regression subset: **30 passed**.
- The 7 skips are the real-data checks that require the protected
  `knowledge/novel-wiki` fixture; they are not production failures. The skip
  condition requires the actual `schema.md` or `wiki/` tree rather than an
  empty sparse-checkout directory.
- The original 26 failures were reduced to zero actionable failures: one
  uninitialized legacy-path audit variable, two outdated publication fixtures,
  and seven protected-fixture assumptions plus their dependent assertions.
- User-level template overrides were isolated with a temporary `USERPROFILE`
  during verification; no user configuration was changed.

## Remaining external item

The prior 15-sample GLM5.2 pilot still has four provider truncation failures.
They remain recorded as failures and must be rerun after provider output
stability/budget is addressed. This integration does not weaken evidence
validation or silently accept those outputs.

## Handoff gate

Before updating `main`, verify the integration branch is clean, there are no
unmerged index entries, the protected paths are absent from the integration
worktree diff, `git diff --check` passes, and the main ref still equals the
recorded baseline. Update `main` only with an old-SHA guarded fast-forward.

Completed: those checks passed and `main` was fast-forwarded with the recorded
old SHA to the verified integration commit. No push was performed.
