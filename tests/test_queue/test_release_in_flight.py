"""Tests for QueueService.release_in_flight — crash-mid-pipeline recovery.

Pre-PR-1 bug: release_in_flight reset RUNNING → PENDING for retry but did
NOT increment ``retry_count``. A pipeline that crashed inside the
finally block (e.g. SIGKILL, OOM, uncaught exception in the generator)
would reset to PENDING with retry_count=0 forever, until the
``snapshot()`` 10-minute stale-reset kicked in (which only handled server
restarts). A persistently-crashing source would retry indefinitely,
burning LLM quota.

After PR-1: every release_in_flight crash path counts as one attempt;
when retry_count reaches MAX_RETRIES the task is dead-lettered inline
(matching the FAILED-exhaustion contract in update_status).
"""

from src.events.event_bus import event_bus
from src.events.events import EventName
from src.queue import (
    __reset_for_testing,
    enqueue_task,
    get_default_queue_service,
    get_queue,
)
from src.queue.retry import MAX_RETRIES
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


DEAD_LETTER_CAPTURE = []


def _on_dead_letter(payload):
    DEAD_LETTER_CAPTURE.append(payload)


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()
    svc = get_default_queue_service()
    svc.pause()
    DEAD_LETTER_CAPTURE.clear()
    handlers = event_bus._handlers.setdefault(EventName.TASK_DEAD_LETTER, set())
    handlers.add(_on_dead_letter)
    # Clean circuit breaker so the test does not inherit an OPEN state.
    from src.circuit_breaker import get_circuit_breaker, CircuitState
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0


def teardown_function(_):
    handlers = event_bus._handlers.get(EventName.TASK_DEAD_LETTER, set())
    handlers.discard(_on_dead_letter)


def _acquire_and_force_running(task_id: str) -> None:
    """Simulate the dispatcher having acquired the task and moved it to
    RUNNING in-memory (without going through update_status)."""
    svc = get_default_queue_service()
    svc.tracker.acquire(task_id)
    task = svc.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    svc.backend.save(task)


def test_release_in_flight_increments_retry_count_on_crash(tmp_path, monkeypatch):
    """When the pipeline crashes mid-run (finally-only release_in_flight
    call), the reset RUNNING → PENDING increments retry_count."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("crash.md", SourceType.FILE, "hash-crash-1")
    _acquire_and_force_running(task_id)

    assert svc.backend.find(task_id).retry_count == 0

    svc.release_in_flight(task_id)

    task = svc.backend.find(task_id)
    assert task.status is TaskStatus.PENDING
    assert task.retry_count == 1, (
        f"crash should count as one attempt, got retry_count={task.retry_count}"
    )


def test_release_in_flight_caps_retries_at_max(tmp_path, monkeypatch):
    """MAX_RETRIES consecutive crashes (with the scheduler redispatching each
    time) must dead-letter, not loop indefinitely."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("loop.md", SourceType.FILE, "hash-loop")

    # Simulate MAX_RETRIES crashes: dispatcher crashes every time before
    # calling update_status, then release_in_flight is called from finally.
    for attempt in range(MAX_RETRIES):
        _acquire_and_force_running(task_id)
        # update_status to RUNNING is illegal at this point because the task
        # is already RUNNING — but the real dispatcher path is the same: it
        # crashed before any state transition happened. We just want the
        # release_in_flight reset path.
        svc.release_in_flight(task_id)
        task = svc.backend.find(task_id)
        if task.status is TaskStatus.DEAD_LETTER:
            break
        # The dispatcher would re-pick this PENDING task and re-acquire for
        # the next "crash" iteration.
    else:
        # Did not break out of the loop — assert specific reason.
        raise AssertionError(
            f"after {MAX_RETRIES} releases, task should be DEAD_LETTER, "
            f"got status={svc.backend.find(task_id).status}"
        )

    task = svc.backend.find(task_id)
    assert task.status is TaskStatus.DEAD_LETTER
    assert task.retry_count >= MAX_RETRIES
    # The error message must carry the no-retry marker so the queue's retry
    # policy treats the crash-exhaustion as terminal.
    assert task.error is not None
    from src.lib.errors import NO_RETRY_MARKER
    assert task.error.startswith(NO_RETRY_MARKER), (
        f"expected no-retry marker in error, got {task.error!r}"
    )


def test_release_in_flight_emits_dead_letter_event_on_exhaustion(tmp_path, monkeypatch):
    """The crash-exhaustion dead-letter path must emit task:dead_letter."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("exhaust.md", SourceType.FILE, "hash-exhaust")

    for _ in range(MAX_RETRIES):
        _acquire_and_force_running(task_id)
        svc.release_in_flight(task_id)
        if svc.backend.find(task_id).status is TaskStatus.DEAD_LETTER:
            break

    assert DEAD_LETTER_CAPTURE, "task:dead_letter event was not emitted"
    payload = DEAD_LETTER_CAPTURE[-1]
    assert payload.task_id == task_id
    assert payload.retry_count >= MAX_RETRIES
    assert payload.error  # non-empty


def test_release_in_flight_clears_idempotency_hash_on_dead_letter(tmp_path, monkeypatch):
    """Dead-letter via release_in_flight must allow re-enqueuing the same
    source later (same contract as update_status → DEAD_LETTER)."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_hash = "hash-clear-test"
    task_id = enqueue_task("clear.md", SourceType.FILE, task_hash)
    # Pre-mark the hash as already-seen (simulating the in-memory cache state).
    from src.utils.idempotency import get_idempotency_cache
    get_idempotency_cache()._cache[task_hash] = 0.0
    # Force 3 crashes.
    for _ in range(MAX_RETRIES):
        _acquire_and_force_running(task_id)
        svc.release_in_flight(task_id)
        if svc.backend.find(task_id).status is TaskStatus.DEAD_LETTER:
            break
    # On re-enqueue, the in-memory idempotency cache must no longer hold this hash.
    assert task_hash not in get_idempotency_cache()._cache, (
        "idempotency hash should be cleared by dead-letter"
    )


def test_release_in_flight_no_op_for_clean_tasks(tmp_path, monkeypatch):
    """A successful pipeline's finally-block calls release_in_flight after
    the task has already been transitioned away from RUNNING (via
    update_status). The release must NOT spuriously increment retry_count
    or trigger an advance on a terminated task."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("clean.md", SourceType.FILE, "hash-clean")

    # Drive the task PENDING → RUNNING → APPROVED via the state machine.
    # Note: _acquire_and_force_running is NOT called here — the dispatcher
    # acquires the tracker as part of its normal flow (select_next_task →
    # tracker.acquire → emit collector:start). For this test we simulate
    # the tracker being released automatically by update_status.
    svc.tracker.acquire(task_id)
    svc.update_status(task_id, TaskStatus.RUNNING)
    svc.update_status(task_id, TaskStatus.APPROVED)
    # At this point update_status(APPROVED) has already released the
    # tracker (no PENDING transition), but the dispatcher's finally
    # unconditionally calls release_in_flight as a defence-in-depth.
    retry_count_before = svc.backend.find(task_id).retry_count
    svc.release_in_flight(task_id)
    retry_count_after = svc.backend.find(task_id).retry_count

    assert retry_count_before == retry_count_after, (
        "release_in_flight must not increment retry_count for completed tasks"
    )
    assert svc.backend.find(task_id).status is TaskStatus.APPROVED
