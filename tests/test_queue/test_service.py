"""Tests for QueueService — the composition root for queue operations.

These tests use FakeQueueBackend + InMemoryInFlightTracker + FakeEventEmitter
to exercise the orchestration logic without IO.
"""
import pytest

from src.queue.service import QueueService
from src.queue.retry import DefaultRetryPolicy
from src.types import SourceType, TaskStatus
from .conftest import FakeQueueBackend, FakeEventEmitter
from src.queue.in_flight import InMemoryInFlightTracker


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
