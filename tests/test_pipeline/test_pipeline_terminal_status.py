import pytest

from src.events.events import CollectorDonePayload
from src.pipeline import pipeline as pipeline_mod
from src.queue import (
    __reset_for_testing,
    enqueue_task,
    get_default_queue_service,
    get_queue,
)
from src.queue.retry import MAX_RETRIES
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()
    get_default_queue_service().pause()


@pytest.mark.asyncio
async def test_handler_marks_task_approved_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = get_default_queue_service()
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-success")
    # Drive the task to RUNNING + in-flight
    task = service.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    service.backend.save(task)
    service.tracker.acquire(task_id)
    # Audit I5: _resolve_wiki_paths now takes project_id kwarg.
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    async def successful_ingest(**kwargs):
        return []

    monkeypatch.setattr(pipeline_mod, "run_ingest", successful_ingest)
    payload = CollectorDonePayload(task_id=task_id, raw_path="source.txt", content="content")

    await pipeline_mod._on_collector_done(payload)

    # APPROVED tasks are filtered from snapshot() (spec invariant), so
    # read the task directly from the backend to verify the transition.
    task = service.backend.find(task_id)
    assert task is not None
    assert task.status is TaskStatus.APPROVED
    assert task_id not in service.tracker.snapshot()


@pytest.mark.asyncio
async def test_handler_marks_task_failed_on_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = get_default_queue_service()
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-failure")
    # Drive the task to RUNNING + in-flight
    task = service.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    service.backend.save(task)
    service.tracker.acquire(task_id)
    # retry_count is set to MAX_RETRIES - 1 so the very next FAILED transition
    # increments it to MAX_RETRIES, dead-lettering the task (per I-queue-11).
    task.retry_count = MAX_RETRIES - 1
    service.backend.save(task)
    # Audit I5: _resolve_wiki_paths now takes project_id kwarg.
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    async def failed_ingest(**kwargs):
        raise RuntimeError("ingest exploded")

    monkeypatch.setattr(pipeline_mod, "run_ingest", failed_ingest)
    payload = CollectorDonePayload(task_id=task_id, raw_path="source.txt", content="content")

    await pipeline_mod._on_collector_done(payload)

    task = get_queue()[0]
    # Once retry_count hits MAX_RETRIES, the queue flips the task to
    # DEAD_LETTER (formerly FAILED).
    assert task.status is TaskStatus.DEAD_LETTER
    assert task.retry_count >= MAX_RETRIES
    assert task.error == "RuntimeError: ingest exploded"
    assert task_id not in service.tracker.snapshot()