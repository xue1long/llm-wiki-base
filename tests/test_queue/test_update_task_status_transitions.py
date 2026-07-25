"""Tests for update_task_status state-machine validation.

After the queue refactor (Tasks 1-7), the production code path goes
through QueueService.update_status, which uses src.queue.state.can_transition.
This test exercises the public API directly (no internal queue state).
"""
import pytest

from src.queue import (
    __reset_for_testing,
    enqueue_task,
    get_default_queue_service,
    get_queue,
    update_task_status,
)
from src.queue.state import InvalidTransition
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    """Test isolation: clear idempotency cache, reset queue singleton,
    and pause the queue so the pipeline service's collector:start handler
    does not auto-dispatch a freshly-enqueued task and drive it to
    FAILED before the test can mutate the status explicitly."""
    get_idempotency_cache().clear()
    __reset_for_testing()
    get_default_queue_service().pause()


def test_pending_to_running_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")

    update_task_status(task_id, TaskStatus.RUNNING)

    assert get_queue()[0].status is TaskStatus.RUNNING


def test_running_to_approved_allowed_for_terminal_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")
    update_task_status(task_id, TaskStatus.RUNNING)

    update_task_status(task_id, TaskStatus.APPROVED)

    # After Tasks 1-7: APPROVED tasks are filtered out of snapshot() (the
    # production invariant from spec). Verify the transition succeeded by
    # reading directly from the backend.
    from src.queue import get_default_queue_service
    service = get_default_queue_service()
    task = service.backend.find(task_id)
    assert task is not None
    assert task.status is TaskStatus.APPROVED


def test_pending_to_approved_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-invalid")

    with pytest.raises(InvalidTransition) as exc_info:
        update_task_status(task_id, TaskStatus.APPROVED)

    assert exc_info.value.args == (task_id, "pending", "approved")
    assert get_queue()[0].status is TaskStatus.PENDING


def test_missing_task_raises_key_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(KeyError, match="missing"):
        update_task_status("missing", TaskStatus.RUNNING)


def test_error_is_recorded_on_valid_transition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")

    update_task_status(task_id, TaskStatus.RUNNING, error="collector warning")

    assert get_queue()[0].error == "collector warning"