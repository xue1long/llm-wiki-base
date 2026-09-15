# V7 ingestion control-plane refactor — 2026-09-15

## Outcome

Completed the source-outcome control-plane hardening for V7 extraction. The
runner now requires an explicit `--root`, serializes per-source outcomes under
the project root, reconciles Writer page outcomes, protects queue writes with
the existing per-root lock, and exposes direct report counts for written,
blocked, failed, incomplete, skipped, and generated pages.

## Durable rules

- Source checkpoint v2 is `root/.index/v7_full_checkpoint.json` when the
  default is used; legacy `completed_batches` never hides a source.
- A corrupt checkpoint is preserved as `.json.corrupt` before recovery.
- Review queue defaults to `root/.index/reviews_queue.json`; custom roots do
  not fall back to the process CWD.
- Source `attempts` count source-level runs; internal Stage/Writer retries do
  not increment the source count. `max_attempts` defaults to 5.
- Stage 6 relation extraction is optional best-effort postprocessing and is not
  part of the first-pass source→concept durable outcome.

## Verification

- Focused V7 suite: `298 passed, 1 skipped in 8.34s`.
- Single-source temporary-root apply smoke: `1 passed in 3.03s`; the second
  apply reported `skipped=1` and did not duplicate queue items. The raw MD5,
  generated page, and source checkpoint remained consistent.
- `compileall` and `git diff --check` passed.
- No external provider was invoked against formal production raw. `_legacy.py`
  remains the accepted out-of-scope placeholder.
