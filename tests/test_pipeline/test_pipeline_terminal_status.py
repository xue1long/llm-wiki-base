import pytest

from src.events.events import CollectorDonePayload
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


@pytest.mark.asyncio
async def test_handler_marks_task_approved_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-success")
    queue_mod._in_flight.add(task_id)
    queue_mod._queue[0].status = TaskStatus.RUNNING
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: object())

    async def successful_ingest(**kwargs):
        return []

    monkeypatch.setattr(pipeline_mod, "run_ingest", successful_ingest)
    payload = CollectorDonePayload(task_id=task_id, raw_path="source.txt", content="content")

    await pipeline_mod._on_collector_done(payload)

    task = get_queue()[0]
    assert task.status is TaskStatus.APPROVED
    assert task_id not in queue_mod._in_flight


@pytest.mark.asyncio
async def test_handler_marks_task_failed_on_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task_id = enqueue_task("source.txt", SourceType.FILE, "hash-failure")
    queue_mod._in_flight.add(task_id)
    queue_mod._queue[0].status = TaskStatus.RUNNING
    # retry_count is set to MAX_RETRIES - 1 so the very next FAILED transition
    # increments it to MAX_RETRIES, dead-lettering the task (per I-queue-11).
    queue_mod._queue[0].retry_count = queue_mod.MAX_RETRIES - 1
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda: tmp_path)
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
    assert task.retry_count >= queue_mod.MAX_RETRIES
    assert task.error == "ingest exploded"
    assert task_id not in queue_mod._in_flight
