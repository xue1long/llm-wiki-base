# Task 7 (audit-fix pass 2) fix report — Critical async/sync cancellation

## Status

Status: DONE
Approach: skip EventBus for the COLLECTOR_DONE handoff (Option 2 in the brief)
Commits: <one commit on `fix/2026-07-23-full-audit`; see `git log -1` after the run>
Test summary: full suite 534 passed; 5/5 targeted pipeline regression tests green; an
independent sync end-to-end smoke test exercises the production chain from a
thread without a running loop.

## What was wrong

The previous fixer wired `_on_collector_done` as the `EventBus` handler for
`COLLECTOR_DONE` via a synchronous adapter that called `loop.create_task(coro)`
when a loop was already running. That path is correct under a *persistent*
loop (the test added in pass 1 used `asyncio.run`-driven code that ended up
on the same loop as the dispatcher, so the child task survived). It is
broken under the production chain:

1. `enqueue_task(...)` is called from a sync thread with no running loop.
2. The queue emits `collector:start`; the sync handler `_dispatch_collector_start`
   sees no running loop and calls `asyncio.run(_on_collector_start(payload))`,
   which spins up a *temporary* loop.
3. Inside that temporary loop, `_on_collector_start` awaits `collect(...)`.
4. `collect(...)` emits `COLLECTOR_DONE` synchronously.
5. The bus dispatch fires `_dispatch_collector_done`, which now finds the
   temporary loop running and does `loop.create_task(_on_collector_done(payload))`.
6. `collect(...)` returns; `_on_collector_start` returns;
   `asyncio.run(main)` returns and *closes the temporary loop, cancelling
   every outstanding task including the scheduled `_on_collector_done`*. The
   child task never finishes; the task status stays `RUNNING`, and `_in_flight`
   is released by cancellation.

The instruction also correctly rules out the brief's `run_until_complete`
alternative: calling `loop.run_until_complete(...)` from inside a coroutine
that is *already being driven* by an event loop raises
`RuntimeError("This event loop is already running")`. So the only safe fix
is to keep the entire chain on one coroutine.

## What I changed

`src/pipeline/pipeline.py`:

* Removed `_dispatch_collector_done` entirely and unregistered it from the
  bus. `collect()` still emits `EventName.COLLECTOR_DONE` on the bus for any
  external subscribers (verified by `test_event_bus_dispatch_external_listener_runs`),
  but the pipeline-internal `_on_collector_done` handler is no longer
  bus-driven.
* Rewrote `_on_collector_start` to be the *single* coroutine driving both
  stages of the chain. After `await collect(...)` returns its
  `CollectorDonePayload`, the same coroutine directly `await`s
  `_on_collector_done(payload)`. The temporary `asyncio.run` loop cannot
  fire-and-forget anything because there are no fire-and-forget tasks.
* Folded the failure-handling logic of the old `_schedule_collector` into
  `_on_collector_start` so the chain always reaches a terminal state
  (`APPROVED`/`FAILED`) and `_in_flight` is always cleared.
* Documented in the module docstring / `_dispatch_collector_start` body
  *why* the previous `create_task` design broke under `asyncio.run`.
* Kept the persistent-loop branch in `_dispatch_collector_start`
  (`loop.create_task(coro)`), since the same single-coroutine chain handles
  it correctly when wrapped by an explicit `await` from the caller.

`tests/test_pipeline/test_pipeline_event_bus_integration.py`:

* Replaced the bus-only regression test (which only exercised the asyncio.run
  fallback in the dispatcher and missed the production chain) with three
  tests:

  1. `test_event_bus_dispatch_external_listener_runs` — confirms external
     subscribers on `COLLECTOR_DONE` still fire.
  2. `test_sync_enqueue_full_chain_runs_to_completion_no_running_loop` —
     the regression that previously failed. Calls `enqueue_task("source.txt",
     FILE, ...)` from a thread with no running loop, monkeypatches
     `collect`, `run_ingest`, `_resolve_wiki_paths`, and `_get_provider`,
     and asserts:

       - `collect()` was invoked exactly once
       - `run_ingest` was invoked exactly once
       - `task.status is TaskStatus.APPROVED`
       - `task_id not in _in_flight`
       - no `RuntimeWarning: coroutine '...' was never awaited` (the original
         bug signature)

  3. `test_sync_enqueue_full_chain_when_run_ingest_raises` — same chain,
     but `run_ingest` raises. Asserts the chain still reaches a terminal
     `FAILED` state and `_in_flight` is cleared.

* Added a `setup_function` / `teardown_function` pair that resets the queue
  circuit breaker to a known-good (CLOSED) state. The new failing-ingest
  test deliberately trips `record_failure()` twice; without the reset the
  breaker would be left OPEN for downstream tests such as
  `test_queue_retry_liveness::test_failed_retry_wakes_process_next`, which
  expects `_process_next` to advance. The reset is local to this module and
  is non-invasive.

## Why "skip EventBus" rather than `run_until_complete`

The brief offered `run_until_complete(...)` as the primary alternative and
"skip EventBus" as a fallback. The fallback is the only viable option here
because:

* `run_until_complete` cannot be called from inside a coroutine that is
  already being driven by the loop — Python raises
  `RuntimeError("This event loop is already running")`. The handler is
  invoked from `event_bus.emit(...)`, which is called from `collect()`,
  which is being driven by the loop. So `run_until_complete` would never
  work in the production chain, regardless of the calling thread.
* `collect()` already returns its `CollectorDonePayload`, so a direct
  in-coroutine handoff requires zero API changes outside `pipeline.py`.

Direct handoff also keeps the failure-handling consistent: the same
try/except/finally in `_on_collector_start` covers both the collector
failure path and the ingest failure path.

## Verification

Focused suite (5/5 green):

```
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib \
  tests/test_pipeline/test_pipeline_event_bus_integration.py \
  tests/test_pipeline/test_pipeline_terminal_status.py -v
```

Full suite (534 passed, 1 third-party StarletteDeprecationWarning):

```
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  PYTHONPATH=. python -m pytest --import-mode=importlib -q
```

## Concerns

None. The change touches only pipeline internals and the test file; no other
module observed `COLLECTOR_DONE` (orchestrator and other listeners wire to
`PROCESSOR_DONE` / `LIBRARIAN_DONE`). The `CollectorDonePayload` type is still
public for scripts that emit it on purpose.
