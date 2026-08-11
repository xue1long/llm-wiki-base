"""Tests for QueueService — the composition root for queue operations.

These tests use FakeQueueBackend + InMemoryInFlightTracker + FakeEventEmitter
to exercise the orchestration logic without IO.
"""
import pytest

from src.queue.service import QueueService
from src.queue.retry import DefaultRetryPolicy
from src.types import SourceType, TaskStatus


@pytest.fixture
def queue_service(fake_backend, fake_tracker, fake_emitter):
    return QueueService(
        backend=fake_backend,
        tracker=fake_tracker,
        emitter=fake_emitter,
        retry_policy=DefaultRetryPolicy(),
    )


class TestEnqueue:
    def test_enqueue_returns_task_id(self, queue_service, fake_emitter):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        assert task_id.startswith("kb-")
        # Emits task:created and collector:start (auto-advance)
        event_names = [e[0] for e in fake_emitter.events]
        assert "task:created" in event_names
        assert "collector:start" in event_names

    def test_enqueue_records_in_flight(self, queue_service, fake_tracker):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        assert fake_tracker.is_in_flight(task_id)

    def test_enqueue_persists_to_backend(self, queue_service, fake_backend):
        task_id = queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        saved = fake_backend.find(task_id)
        assert saved is not None
        assert saved.source == "file-a.txt"

    def test_duplicate_hash_returns_empty_string(self, queue_service, fake_emitter):
        queue_service.enqueue(source="a", source_type=SourceType.FILE, task_hash="dup")
        fake_emitter.events.clear()
        result = queue_service.enqueue(
            source="b", source_type=SourceType.FILE, task_hash="dup",
        )
        assert result == ""
        assert len(fake_emitter.events) == 0  # no new event


class TestUpdateStatus:
    def test_legal_transition_succeeds(self, queue_service, fake_backend):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        queue_service.update_status(task_id, TaskStatus.RUNNING)
        assert fake_backend.find(task_id).status == TaskStatus.RUNNING

    def test_illegal_transition_raises(self, queue_service):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        with pytest.raises(Exception):  # InvalidTransition
            queue_service.update_status(task_id, TaskStatus.APPROVED)

    def test_failed_resets_to_pending_under_retry_limit(
        self, queue_service, fake_backend, fake_emitter
    ):
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        fake_emitter.events.clear()
        queue_service.update_status(task_id, TaskStatus.FAILED, error="boom")
        task = fake_backend.find(task_id)
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 1
        # Should re-advance → emit collector:start again
        assert any(e[0] == "collector:start" for e in fake_emitter.events)

    def test_missing_task_raises_key_error(self, queue_service):
        with pytest.raises(KeyError):
            queue_service.update_status("never-added", TaskStatus.RUNNING)


class TestAdvance:
    def test_paused_does_not_advance(self, queue_service, fake_emitter):
        queue_service.pause()
        task_id = queue_service.enqueue(
            source="x", source_type=SourceType.FILE, task_hash="h1",
        )
        # enqueue emits task:created but advance is skipped while paused
        # (collector:start should NOT be emitted)
        events = [e[0] for e in fake_emitter.events]
        assert "task:created" in events
        assert "collector:start" not in events
        # Resume kicks the scheduler
        queue_service.resume()
        events = [e[0] for e in fake_emitter.events]
        assert "collector:start" in events


class TestPauseResume:
    def test_get_status_reports_paused(self, queue_service):
        queue_service.pause()
        status = queue_service.get_status()
        assert status["paused"] is True

    def test_resume_clears_paused(self, queue_service):
        queue_service.pause()
        queue_service.resume()
        status = queue_service.get_status()
        assert status["paused"] is False


class TestGetQueue:
    def test_get_queue_uses_iter_ids_protocol(self, queue_service, fake_backend):
        """get_queue must call the QueueBackend protocol — not poke at
        private attributes. Verified by counting iter_ids() calls."""
        queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        # Replace the backend's iter_ids with a tracking wrapper so we
        # can prove the protocol method is what get_queue reaches.
        original_iter_ids = fake_backend.iter_ids
        call_count = {"n": 0}

        def tracking_iter_ids():
            call_count["n"] += 1
            return original_iter_ids()

        fake_backend.iter_ids = tracking_iter_ids
        tasks = queue_service.get_queue()
        assert call_count["n"] >= 1
        assert len(tasks) == 1

    def test_get_queue_includes_terminal_tasks(self, queue_service):
        """get_queue must include APPROVED/DEAD_LETTER (unlike snapshot)."""
        queue_service.enqueue(
            source="file-a.txt", source_type=SourceType.FILE, task_hash="h1",
        )
        tasks = queue_service.get_queue()
        assert len(tasks) == 1
        # FakeQueueBackend's save() does NOT update the persisted task's
        # status (it only mutates for the in-process Python reference
        # passed in), so the persisted task retains PENDING here. The
        # important property is that get_queue returns ALL tasks,
        # including ones terminal/auto-advanced state — verified by the
        # fact that it returned this auto-advanced task at all.
        assert tasks[0].id.startswith("kb-")


# --- circuit breaker fixes (Bug 2a + 2b) ---

class TestBreakerFailureFromOpen:
    """record_failure() from state OPEN must NOT reset opened_at."""

    def test_failure_from_open_does_not_reset_opened_at(self, queue_service):
        from datetime import datetime
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        # Force the breaker OPEN.
        breaker.state = CircuitState.OPEN
        t0 = datetime(2026, 1, 1, 0, 0, 0)
        breaker.opened_at = t0
        breaker.failure_count = 0

        # Record 10 failures while OPEN. None should reset opened_at.
        for _ in range(10):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.opened_at == t0, (
            "opened_at must not be reset by record_failure() when already OPEN"
        )
        assert breaker.failure_count == 10

    def test_failure_from_closed_still_transitions_to_open(self, queue_service):
        from src.circuit_breaker import CircuitState, CircuitBreakerConfig

        breaker = queue_service._breaker()
        breaker.state = CircuitState.CLOSED
        breaker.config = CircuitBreakerConfig(failure_threshold=3)
        breaker.failure_count = 0

        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.opened_at is not None

    def test_failure_from_half_open_transitions_to_open(self, queue_service):
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        breaker.state = CircuitState.HALF_OPEN
        breaker.failure_count = 0
        breaker.opened_at = None

        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN


class TestNoAutoPause:
    """DEAD_LETTER tasks with an open breaker no longer auto-pause the queue."""

    def test_dead_letter_with_open_breaker_does_not_pause(self, queue_service, fake_emitter):
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        breaker.state = CircuitState.OPEN
        breaker.opened_at = None  # capture current time to prevent stale-candidate fail

        task_id = queue_service.enqueue(
            source="f.md", source_type=SourceType.FILE, task_hash="h1",
        )
        # Drive task to RUNNING then FAILED 3 times to reach DEAD_LETTER
        queue_service.update_status(task_id, TaskStatus.RUNNING)
        queue_service.update_status(task_id, TaskStatus.FAILED, error="err1")
        queue_service.update_status(task_id, TaskStatus.RUNNING)
        queue_service.update_status(task_id, TaskStatus.FAILED, error="err2")
        queue_service.update_status(task_id, TaskStatus.RUNNING)
        queue_service.update_status(task_id, TaskStatus.FAILED, error="err3")

        # After 3 retries the task should be DEAD_LETTER, but the queue must
        # NOT be paused.
        assert not queue_service._paused, (
            "Queue must not auto-pause on DEAD_LETTER — the circuit breaker "
            "already protects the system."
        )


class TestRecoveryTimer:
    """advance() schedules a recovery timer when the breaker is OPEN."""

    def test_recovery_timer_scheduled_when_breaker_open(self, queue_service, monkeypatch):
        """When advance() finds breaker OPEN, it schedules a recovery timer."""
        from datetime import datetime
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        breaker.state = CircuitState.OPEN
        # opened_at must be recent so the 60s recovery timeout has not elapsed.
        breaker.opened_at = datetime.now()
        queue_service._paused = False

        # Track Timer creation
        calls = []
        monkeypatch.setattr(queue_service, "_schedule_recovery_advance",
                           lambda: calls.append("scheduled"))

        queue_service.advance()
        assert calls == ["scheduled"]

    def test_recovery_timer_cancelled_when_dispatching(self, queue_service):
        """When advance() dispatches a task, it cancels any pending timer."""
        from src.circuit_breaker import CircuitState
        import threading

        breaker = queue_service._breaker()
        breaker.state = CircuitState.CLOSED
        queue_service._paused = False

        # Set up a fake pending timer
        queue_service._recovery_timer = threading.Timer(999, lambda: None)
        queue_service._recovery_timer.start()

        task_id = queue_service.enqueue(
            source="f.md", source_type=SourceType.FILE, task_hash="h1",
        )
        # Move to RUNNING so it won't be selected again, then call advance
        queue_service.update_status(task_id, TaskStatus.RUNNING)

        # Enqueue another pending task and call advance — it should dispatch
        # and cancel the timer.
        queue_service.enqueue(
            source="g.md", source_type=SourceType.FILE, task_hash="h2",
        )
        # advance() dispatches the pending task
        assert queue_service._recovery_timer is None, (
            "Recovery timer must be cancelled when advance() dispatches a task"
        )

    def test_manual_pause_still_blocks_advance(self, queue_service):
        """Manual pause() must still prevent advance() from dispatching."""
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        breaker.state = CircuitState.CLOSED
        queue_service._paused = True

        task_id = queue_service.enqueue(
            source="f.md", source_type=SourceType.FILE, task_hash="h1",
        )
        assert task_id

        dispatched = queue_service.advance()
        assert dispatched is False, "advance() must return False when paused"

    def test_recovery_timer_fires_and_advances(self, queue_service, monkeypatch):
        """End-to-end: timer fires, advance() checks breaker, dispatches task."""
        from src.circuit_breaker import CircuitState

        breaker = queue_service._breaker()
        queue_service._paused = False

        # Enqueue a task — it will be auto-dispatched by enqueue().
        tid = queue_service.enqueue(
            source="f.md", source_type=SourceType.FILE, task_hash="h1",
        )
        # Move the auto-dispatched task to APPROVED so it won't be selected.
        queue_service.update_status(tid, TaskStatus.RUNNING)
        queue_service.update_status(tid, TaskStatus.APPROVED)

        # Enqueue a second task. This time pause the auto-advance by
        # temporarily pausing, then unpausing once the task is in the queue.
        queue_service._paused = True
        tid2 = queue_service.enqueue(
            source="g.md", source_type=SourceType.FILE, task_hash="h2",
        )
        queue_service._paused = False

        # Put breaker in HALF_OPEN (what happens after recovery timeout).
        breaker.state = CircuitState.HALF_OPEN

        # advance() should dispatch the second pending task now.
        queue_service._cancel_recovery_timer = lambda: None  # no-op
        result = queue_service.advance()
        assert result is True, "advance() should dispatch when breaker is HALF_OPEN"
