# Runtime control-plane hardening report

## Scope

Completed the runtime hardening requested by Task 3/4/5 without modifying
Wiki/raw data, progress.md, ADRs, or pre-existing dirty files.

## Implemented

- Made `--root` required for both extraction CLIs; missing root prints usage
  and exits with code 2.
- Wrapped `extract_full.run_full()` with the existing per-root queue lock and
  guaranteed release on normal and exceptional exits. Lock contention aborts
  without removing the other process's lock.
- Changed full extraction from batch-owned completion to per-source handling:
  extract one source, consume its Writer report, reconcile the source outcome,
  then atomically flush the checkpoint.
- Ignored legacy `completed_batches` for resume decisions so an old batch row
  cannot hide a source. `batch_size` now affects grouping/statistics only.
- Added corrupt checkpoint backup to `<checkpoint>.corrupt`, then rebuilt a
  version-2 checkpoint.
- Added source-level `attempts` and `max_attempts` (default 5). One entry into
  `_extract_one()` is one attempt; Stage 5/Writer internal retries do not add
  source attempts. Exhausted failures persist as `failed_max_attempts`.
- Preserved dry-run audit rows without treating them as apply completion.
  A subsequent apply reruns the source; a second unchanged pure-written apply
  reports a source-level skip.
- Reconciled `written_page_ids`, `blocked_page_ids`, `failed_page_ids`, status,
  and error text from `WriteReport.page_writes` after Writer execution.
- Added direct summary fields: `written`, `blocked`, `failed`, `incomplete`,
  `skipped`, and `generated_pages`, while retaining `errors == failed` and the
  existing nested counters.
- Routed pilot Stage 5 and source exceptions to the project-root reviews queue
  through the existing stable/idempotent failure API, including prompt/provider
  triage labels.

## TDD and regression evidence

Tests were added before implementation. The first attempted run with the
system interpreter was blocked before collection because `pytest` (and later
`httpx` during a direct import check) was missing. The repository `.venv` was
then located and used for executable regression checks.

During green-up, the apply smoke produced two real failures that were fixed:

1. The smoke's one-topic cluster left five sections unassigned, correctly
   producing a mixed written/blocked result that must rerun. The fixture now
   assigns all six sections so it represents the intended pure-written skip.
2. A checkpoint replay lacked legacy serialization fields and raised
   `KeyError: 'source'` while writing Markdown. Replay metadata and compatible
   Markdown access were added.

Final commands:

```text
PYTHONPATH=. .venv/Scripts/python.exe -m pytest \
  tests/test_scripts/test_extract_full.py \
  tests/test_scripts/test_extract_pilot.py \
  tests/test_scripts/test_v7_extract_apply_smoke.py \
  tests/test_pipeline/test_v7_extract_wiki_writer.py \
  tests/test_pipeline/test_v7_extract_failures.py -q \
  --basetemp=.tmp-pytest-runtime-hardening-acceptance

93 passed in 5.83s
```

```text
python -m compileall -q scripts/extract_full.py scripts/extract_pilot.py \
  src/pipeline/v7_extract/_queue_lock.py \
  tests/test_scripts/test_extract_full.py \
  tests/test_scripts/test_extract_pilot.py \
  tests/test_scripts/test_v7_extract_apply_smoke.py

exit 0
```

`git diff --check` exited 0. Direct invocations of both scripts without
`--root` printed usage and exited 2. Both `--help` commands show `--root ROOT`
as required and expose the full-runner checkpoint/report options.

## Limitations / unresolved

- No external-provider call against the production raw corpus was made. The
  deterministic one-source apply smoke writes a temporary Wiki, checks raw MD5,
  reconciles report/checkpoint/filesystem state, and verifies the second-run
  skip without network cost or production data mutation.
- The queue lock remains the planned soft PID/O_EXCL hint. A hard kill can
  leave a stale `.queue-lock` that requires manual removal; true multi-process
  queue atomicity remains out of scope.
- Graphify query was attempted but unavailable because its local `uv`
  trampoline could not canonicalize the script path. Source discovery fell
  back to read-only `rg` as permitted by the repository instructions.

Commit message: `fix(v7-extract):runtime-source-control-plane-hardening`.
