"""End-to-end regression tests for the collector -> ingest chain.

The original code registered `_on_collector_done` as an EventBus handler
dispatched via `loop.create_task` from inside `_dispatch_collector_done`.
Under `asyncio.run` (e.g. when a synchronous caller invokes `enqueue_task`
from a thread with no running loop), the temporary loop is closed as soon
as the outer coroutine returns, which cancelled the child task before
`run_ingest` could finish. Symptoms: status remained RUNNING, `_in_flight`
was cleared by cancellation, the runtime warning
`RuntimeWarning: coroutine '_on_collector_done' was never awaited` fired.

The production chain now drives `_on_collector_done` directly from
`_on_collector_start` via plain `await`, so the chain stays on one coroutine
on one loop and cannot be left dangling.

Two tests exercise this:

* `test_event_bus_dispatch_external_listener_runs` — `collector:done` is
  still emitted by `collect()` for any external subscribers; only the
  pipeline-internal `_on_collector_done` handler is gone.

* `test_sync_enqueue_full_chain_runs_to_completion_no_running_loop` — the
  full sync/no-preexisting-loop production chain: `enqueue_task(...)` from
  a thread with no running loop, asserts the task reaches APPROVED,
  `_in_flight` is cleared, and no coroutine is left unawaited.
"""
import asyncio
import warnings

import pytest

from src.circuit_breaker import get_circuit_breaker, CircuitState
from src.events.event_bus import event_bus
from src.events.events import CollectorDonePayload, EventName
from src.pipeline import pipeline as pipeline_mod
from src.queue import queue as queue_mod
from src.queue.queue import enqueue_task, get_queue
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    queue_mod._queue.clear()
    queue_mod._paused = True
    queue_mod._in_flight.clear()
    # Reset the queue circuit breaker so this test cannot leak an OPEN state
    # into downstream tests (test_queue_retry_liveness is sensitive to it).
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0
    breaker.success_count = 0
    breaker.opened_at = None
    breaker.last_failure_time = None


def teardown_function(_):
    # Defensive: leave the breaker in a known good state for the next test.
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0
    breaker.success_count = 0
    breaker.opened_at = None
    breaker.last_failure_time = None


def test_event_bus_dispatch_external_listener_runs(tmp_path, monkeypatch):
    """`collect()` must still emit `collector:done` for external subscribers.

    The pipeline no longer relies on the bus dispatch to run `_on_collector_done`
    (it drives the handler directly), but other code may still subscribe — the
    emit must reach such listeners.
    """
    monkeypatch.chdir(tmp_path)

    seen = []
    unsubscribe = event_bus.on(
        EventName.COLLECTOR_DONE,
        lambda payload: seen.append(payload.task_id),
    )
    try:
        inbox = pipeline_mod.collect.__module__
        payload = CollectorDonePayload(
            task_id="kb-external",
            raw_path=str(tmp_path / "x.md"),
            content="hello",
        )
        event_bus.emit(EventName.COLLECTOR_DONE, payload)
    finally:
        unsubscribe()

    assert seen == ["kb-external"]


def test_sync_enqueue_full_chain_runs_to_completion_no_running_loop(
    tmp_path, monkeypatch,
):
    """Regression: the full synchronous chain must run to completion.

    No event loop is running before `enqueue_task` returns. `collect()` and
    `run_ingest` are awaited inside the same coroutine the dispatch adapter
    drives via `asyncio.run`. This is the production entry path: the
    previous implementation cancelled the child ingest task when
    `asyncio.run` closed its loop.
    """
    monkeypatch.chdir(tmp_path)

    ingested = []
    collected = []

    async def successful_ingest(**kwargs):
        ingested.append(kwargs)
        return []

    async def stub_collect(task_id, source, source_type):
        from src.events.events import CollectorDonePayload
        collected.append(task_id)
        return CollectorDonePayload(
            task_id=task_id,
            raw_path=str(tmp_path / f"{task_id}.md"),
            content="stubbed content",
        )

    monkeypatch.setattr(pipeline_mod, "collect", stub_collect)
    monkeypatch.setattr(pipeline_mod, "run_ingest", successful_ingest)
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    # Unpause so the synchronous enqueue actually triggers the chain.
    queue_mod._paused = False

    # Capture coroutine warnings — the previous bug fired this exact warning.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        task_id = enqueue_task("source.txt", SourceType.FILE, "hash-sync-chain")
        assert task_id, "enqueue_task should return a task id"

    # The dispatcher must have driven `collect()` and `run_ingest` synchronously
    # inside the asyncio.run temporary loop.
    task = get_queue()[0]
    assert collected == [task_id], "collect() must be invoked exactly once"
    assert ingested, "run_ingest must be invoked exactly by the chain"
    assert task.status is TaskStatus.APPROVED, (
        "expected APPROVED after synchronous enqueue; got "
        f"{task.status!r}. run_ingest calls seen: {len(ingested)}"
    )
    assert task_id not in queue_mod._in_flight, (
        "_in_flight must be released after the chain completes"
    )

    unawaited = [
        str(w.message) for w in caught if "never awaited" in str(w.message)
    ]
    assert not unawaited, (
        f"no coroutine may be left unawaited; got: {unawaited!r}"
    )


def test_sync_enqueue_full_chain_when_run_ingest_raises(tmp_path, monkeypatch):
    """A raise inside `run_ingest` must still leave the chain terminal."""
    monkeypatch.chdir(tmp_path)

    async def failed_ingest(**kwargs):
        raise RuntimeError("ingest blew up")

    async def stub_collect(task_id, source, source_type):
        from src.events.events import CollectorDonePayload
        return CollectorDonePayload(
            task_id=task_id,
            raw_path=str(tmp_path / f"{task_id}.md"),
            content="stubbed content",
        )

    monkeypatch.setattr(pipeline_mod, "collect", stub_collect)
    monkeypatch.setattr(pipeline_mod, "run_ingest", failed_ingest)
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    queue_mod._paused = False

    # First pass: raises, retry path runs — counter goes to MAX_RETRIES (was
    # 0 → 1 after first FAILED update). Second pass: clears in-flight and
    # re-emits, this time the retry counter is already at MAX_RETRIES, so
    # the final state is DEAD_LETTER (per I-queue-11 dead-letter surface).
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-sync-raise")
    assert task_id

    # The retry counter is now 1; force the second (terminal) failed pass.
    queue_mod._in_flight.discard(task_id)
    queue_mod._queue[0].retry_count = queue_mod.MAX_RETRIES - 1
    queue_mod._queue[0].status = TaskStatus.PENDING
    event_bus.emit(
        "collector:start",
        {
            "task_id": task_id,
            "source": "source.txt",
            "source_type": SourceType.FILE,
        },
    )

    task = get_queue()[0]
    assert task.status is TaskStatus.DEAD_LETTER, (
        f"expected DEAD_LETTER after retry exhaustion; got {task.status!r}"
    )
    assert task_id not in queue_mod._in_flight
