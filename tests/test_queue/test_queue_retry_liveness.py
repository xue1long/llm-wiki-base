"""Verify queue liveness on retry + deadlock-free event emission.

Two scenarios that the prior implementation missed:
1. A FAILED-then-retried task must be picked up by the scheduler after
   the status flips back to PENDING — not left stranded until the next
   enqueue.
2. update_task_status must release the queue lock before emitting
   TASK_STATUS_CHANGED, so any synchronous handler that re-enters the
   queue (e.g. via get_queue) does not deadlock.

After the queue refactor (Tasks 1-7), the production code path goes
through QueueService.update_status, which holds a service-level lock
for the multi-step orchestration and releases it before emitting. The
default service singleton is process-wide; this test exercises the
singleton directly with the JsonFileBackend pointing at a per-test
tmp_path (handled by the conftest autouse fixture).
"""
from src.events.event_bus import event_bus
from src.events.events import EventName
from src.queue import __reset_for_testing, enqueue_task, get_default_queue_service, update_task_status
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()


def test_failed_retry_wakes_scheduler(tmp_path, monkeypatch):
    """A retried PENDING task must be picked up without an extra enqueue."""
    monkeypatch.chdir(tmp_path)
    service = get_default_queue_service()

    # Capture events on the singleton bus, BEFORE enqueue, so the initial
    # task:created / collector:start are also captured.
    bus_events = []
    monkeypatch.setattr(
        event_bus, "emit", lambda name, payload: bus_events.append((name, payload))
    )

    task_id = service.enqueue("retry.txt", SourceType.FILE, "hash-retry")
    # Drain the initial scheduler run — manually release in-flight and
    # flip the task to RUNNING so the next FAILED transition is valid.
    service.tracker.release(task_id)
    task = service.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    service.backend.save(task)
    bus_events.clear()

    # Now flip to FAILED under the retry limit.
    service.update_status(task_id, TaskStatus.FAILED, error="boom")

    # The retry should have set status back to PENDING AND emitted a
    # collector:start via service.advance() (in-flight was released).
    task = service.backend.find(task_id)
    assert task.status is TaskStatus.PENDING
    assert task.retry_count == 1
    assert any(name == "collector:start" for name, _ in bus_events), bus_events


def test_status_changed_emitted_after_lock_release(tmp_path, monkeypatch):
    """A TASK_STATUS_CHANGED handler may safely re-enter the queue."""
    monkeypatch.chdir(tmp_path)
    service = get_default_queue_service()

    task_id = service.enqueue("reentry.txt", SourceType.FILE, "hash-reentry")
    service.tracker.release(task_id)
    task = service.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    service.backend.save(task)

    reentered = []

    def on_status_change(payload):
        # Synchronous handler that calls back into the queue. If the lock
        # were still held by update_task_status, this would deadlock.
        reentered.append(service.get_queue())

    # Subscribe to TASK_STATUS_CHANGED via the singleton event bus.
    handlers = event_bus._handlers.setdefault(EventName.TASK_STATUS_CHANGED, set())
    handlers.add(on_status_change)
    try:
        service.update_status(task_id, TaskStatus.APPROVED)
        assert reentered, "handler should have re-entered the queue without deadlock"
    finally:
        handlers.discard(on_status_change)