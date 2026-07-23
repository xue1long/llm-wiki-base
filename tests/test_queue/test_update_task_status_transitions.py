import pytest

from src.queue import queue as queue_module
from src.queue.queue import (
    InvalidTransition,
    __reset_for_testing,
    enqueue_task,
    get_queue,
    update_task_status,
)
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()
    queue_module._paused = True


def test_pending_to_running_allowed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")

    update_task_status(task_id, TaskStatus.RUNNING)

    assert get_queue()[0].status is TaskStatus.RUNNING


def test_running_to_approved_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")
    update_task_status(task_id, TaskStatus.RUNNING)

    with pytest.raises(InvalidTransition) as exc_info:
        update_task_status(task_id, TaskStatus.APPROVED)

    assert exc_info.value.args == (task_id, "running", "approved")
    assert get_queue()[0].status is TaskStatus.RUNNING


def test_missing_task_raises_key_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(KeyError, match="missing"):
        update_task_status("missing", TaskStatus.RUNNING)


def test_error_is_recorded_on_valid_transition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")

    update_task_status(task_id, TaskStatus.RUNNING, error="collector warning")

    assert get_queue()[0].error == "collector warning"
