# tests/test_queue/test_dead_letter.py
"""Tests for queue dead-letter surface.

Per I-queue-11 (full audit): once a task exhausts MAX_RETRIES, the queue must
emit a `task:dead_letter` event with {task_id, retry_count, last_error} and
transition the task to TaskStatus.DEAD_LETTER (not just FAILED).
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


# Module-level capture for events emitted during dead-letter handling.
DEAD_LETTER_CAPTURE = []


def _on_dead_letter(payload):
    DEAD_LETTER_CAPTURE.append(payload)


def _subscribe():
    q.event_bus._handlers.setdefault("task:dead_letter", set()).add(_on_dead_letter)


def _unsubscribe():
    handlers = q.event_bus._handlers.get("task:dead_letter", set())
    handlers.discard(_on_dead_letter)


def _reset_circuit_breaker():
    """Reset the queue's circuit breaker so tests don't inherit an OPEN state."""
    from src.circuit_breaker import get_circuit_breaker, CircuitState
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0
    breaker.success_count = 0
    breaker.opened_at = None


def setup_function(_):
    """Test isolation: clear queue, in-flight, idempotency cache, event capture,
    and re-register the dead-letter subscriber on the singleton event bus."""
    get_idempotency_cache().clear()
    q._queue.clear()
    q._paused = True
    q._in_flight.clear()
    DEAD_LETTER_CAPTURE.clear()
    _reset_circuit_breaker()
    _unsubscribe()
    _subscribe()


def teardown_function(_):
    """Clean up: remove our handler so it doesn't leak between tests."""
    _unsubscribe()
    _reset_circuit_breaker()


def _drive_to_running(task_id: str) -> None:
    """Move a freshly enqueued task to RUNNING without going through the
    state-machine validator (which rejects RUNNING→RUNNING)."""
    update_task_status(task_id, TaskStatus.RUNNING)


def _reset_to_running(task_id: str) -> None:
    """After a FAILED→PENDING auto-retry, force the task back to RUNNING so
    the next FAILED transition is valid."""
    task = next((t for t in q._queue if t.id == task_id), None)
    assert task is not None
    task.status = TaskStatus.RUNNING


def test_dead_letter_emitted_on_retry_exhaustion(tmp_path, monkeypatch):
    """Once retry_count reaches MAX_RETRIES, queue emits task:dead_letter."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("boom.txt", SourceType.FILE, "hash-boom")

    _drive_to_running(task_id)

    last_error = "simulated collector failure"
    # Drive retries to exhaustion. Each FAILED increments retry_count.
    update_task_status(task_id, TaskStatus.FAILED, error=last_error)  # retry 1 → PENDING
    _reset_to_running(task_id)
    update_task_status(task_id, TaskStatus.FAILED, error=last_error)  # retry 2 → PENDING
    _reset_to_running(task_id)
    update_task_status(task_id, TaskStatus.FAILED, error=last_error)  # retry 3 → DEAD_LETTER

    assert DEAD_LETTER_CAPTURE, "task:dead_letter event was never emitted"
    payload = DEAD_LETTER_CAPTURE[-1]
    assert payload["task_id"] == task_id
    assert payload["retry_count"] >= q.MAX_RETRIES
    assert payload["last_error"] == last_error


def test_dead_letter_status_assigned(tmp_path, monkeypatch):
    """After retry exhaustion, the task itself is in TaskStatus.DEAD_LETTER."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("boom.txt", SourceType.FILE, "hash-boom")

    _drive_to_running(task_id)
    # Drive retries to (but not past) the exhaustion threshold; on the final
    # FAILED transition the queue flips the status to DEAD_LETTER.
    for _ in range(q.MAX_RETRIES):
        update_task_status(task_id, TaskStatus.FAILED, error="boom")
        # If we've been dead-lettered, stop — additional FAILED transitions
        # would be invalid (DEAD_LETTER has no outgoing edge to FAILED).
        task = next((t for t in q._queue if t.id == task_id), None)
        if task is not None and task.status == TaskStatus.DEAD_LETTER:
            break
        _reset_to_running(task_id)

    tasks = [t for t in get_queue() if t.id == task_id]
    assert tasks
    assert tasks[0].status == TaskStatus.DEAD_LETTER


def test_dead_letter_not_emitted_below_threshold(tmp_path, monkeypatch):
    """A FAILED transition that still has retries left does NOT emit dead-letter."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("recover.txt", SourceType.FILE, "hash-recover")

    _drive_to_running(task_id)
    update_task_status(task_id, TaskStatus.FAILED, error="first failure")

    assert not DEAD_LETTER_CAPTURE
    tasks = [t for t in get_queue() if t.id == task_id]
    assert tasks
    assert tasks[0].status == TaskStatus.PENDING
    assert tasks[0].retry_count == 1


def test_dead_letter_concurrent_retries(tmp_path, monkeypatch):
    """Concurrent FAILED transitions cannot race past MAX_RETRIES without emitting."""
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("race.txt", SourceType.FILE, "hash-race")
    _drive_to_running(task_id)

    transition_errors = []

    def fire():
        # Each thread fires raw status mutations that may race with the
        # queue's auto-retry flipping status back to PENDING. We only care
        # that the dead-letter event fires at least once and InvalidTransition
        # exceptions are tolerated (they are a state-machine safety feature,
        # not a bug).
        for _ in range(5):
            # Bail early if the task has already been dead-lettered by
            # another thread — no further FAILED transitions are valid.
            task = next((t for t in q._queue if t.id == task_id), None)
            if task is None or task.status == TaskStatus.DEAD_LETTER:
                return
            try:
                update_task_status(task_id, TaskStatus.FAILED, error="race")
            except Exception as exc:  # noqa: BLE001
                transition_errors.append(exc)
            # Skip the reset-to-RUNNING if the FAILED transition already
            # flipped us into DEAD_LETTER — keeping it RUNNING would mask
            # the final dead-letter state for the assertion below.
            task = next((t for t in q._queue if t.id == task_id), None)
            if task is not None and task.status == TaskStatus.DEAD_LETTER:
                return
            _reset_to_running(task_id)

    threads = [threading.Thread(target=fire) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All transition errors are expected (race condition safety feature).
    assert all(e.__class__.__name__ == "InvalidTransition" for e in transition_errors), \
        f"unexpected errors: {transition_errors}"
    # At least one dead-letter emission should have occurred.
    assert DEAD_LETTER_CAPTURE, "concurrent retries did not trigger dead-letter"
    tasks = [t for t in get_queue() if t.id == task_id]
    assert tasks
    assert tasks[0].status == TaskStatus.DEAD_LETTER