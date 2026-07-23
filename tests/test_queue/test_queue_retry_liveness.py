"""Verify queue liveness on retry + deadlock-free event emission.

Two scenarios that the prior implementation missed:
1. A FAILED-then-retried task must be picked up by _process_next after the
   status flips back to PENDING — not left stranded until the next enqueue.
2. update_task_status must release the queue lock before emitting
   TASK_STATUS_CHANGED, so any synchronous handler that re-enters the queue
   (e.g. via get_queue) does not deadlock.
"""
import threading

from src.queue import queue as q
from src.queue.queue import (
    __reset_for_testing,
    enqueue_task,
    get_queue,
    update_task_status,
)
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    q._queue.clear()
    q._paused = True
    q._in_flight.clear()
    __reset_for_testing()


def test_failed_retry_wakes_process_next(tmp_path, monkeypatch):
    """A retried PENDING task must be picked up without an extra enqueue."""
    monkeypatch.chdir(tmp_path)

    # Capture which tasks _process_next would dispatch BEFORE enqueue_task,
    # so the initial collector:start emitted by enqueue is also captured
    # (rather than triggering a real collector chain via _on_collector_start).
    emitted = []
    monkeypatch.setattr(q.event_bus, "emit", lambda *args: emitted.append(args))

    q._paused = False  # allow _process_next to dispatch
    task_id = enqueue_task("retry.txt", SourceType.FILE, "hash-retry")

    # Drain the initial _process_next that enqueue_task fires.
    q._in_flight.discard(task_id)
    q._queue[0].status = TaskStatus.RUNNING
    emitted.clear()

    # Now flip the task to FAILED, but well under MAX_RETRIES so it auto-retries.
    update_task_status(task_id, TaskStatus.FAILED, error="boom")

    # The retry should have set status back to PENDING AND emitted a
    # collector:start via _process_next (the in-flight discard allowed the
    # same task to be re-dispatched immediately on the retry).
    assert q._queue[0].status is TaskStatus.PENDING
    assert q._queue[0].retry_count == 1
    assert any(name == "collector:start" for name, _ in emitted), emitted


def test_status_changed_emitted_after_lock_release(tmp_path, monkeypatch):
    """A TASK_STATUS_CHANGED handler may safely re-enter the queue."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("reentry.txt", SourceType.FILE, "hash-reentry")
    q._in_flight.discard(task_id)
    q._queue[0].status = TaskStatus.RUNNING

    reentered = []

    def on_status_change(payload):
        # Synchronous handler that calls back into the queue. If the lock
        # were still held by update_task_status, this would deadlock.
        reentered.append(get_queue())

    from src.events.events import EventName
    monkeypatch.setattr(q.event_bus, "on", lambda name, fn: None)
    # Subscribe via a fresh bus instance reference; easier: just call update.
    q.event_bus._handlers.setdefault(EventName.TASK_STATUS_CHANGED, set()).add(
        on_status_change
    )

    update_task_status(task_id, TaskStatus.APPROVED)
    assert reentered, "handler should have re-entered the queue without deadlock"