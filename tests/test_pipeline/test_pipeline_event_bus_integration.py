"""End-to-end integration test for collector:done dispatch via the EventBus.

The previous implementation registered the async `_on_collector_done` handler as
`lambda p: _on_collector_done(p)`. `EventBus.emit()` is synchronous and merely
calls each handler — it does not await the returned coroutine. Result:
`run_ingest` never ran in production and the warning
`RuntimeWarning: coroutine '_on_collector_done' was never awaited` was emitted.

This test verifies that emitting `COLLECTOR_DONE` through `event_bus.emit`
actually triggers `run_ingest` (the coroutine runs, not just the lambda).
"""
import asyncio

import pytest

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


def test_event_bus_dispatch_invokes_run_ingest(tmp_path, monkeypatch):
    """Emitting COLLECTOR_DONE via the bus must actually call run_ingest."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-bus")
    queue_mod._in_flight.add(task_id)
    queue_mod._queue[0].status = TaskStatus.RUNNING
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    ingested = []

    async def successful_ingest(**kwargs):
        ingested.append(kwargs)
        return []

    monkeypatch.setattr(pipeline_mod, "run_ingest", successful_ingest)
    payload = CollectorDonePayload(task_id=task_id, raw_path="source.txt", content="c")

    event_bus.emit(EventName.COLLECTOR_DONE, payload)

    # If the bus actually invokes the async handler (rather than discarding the
    # coroutine), at least one scheduled task was created. Drain it.
    loop = asyncio.new_event_loop()
    try:
        for task in asyncio.all_tasks(loop):
            try:
                loop.run_until_complete(task)
            except Exception:
                pass
    finally:
        loop.close()

    assert ingested, "EventBus.emit must invoke the async collector:done handler"
    assert task_id not in queue_mod._in_flight, "_in_flight must be released after ingest"