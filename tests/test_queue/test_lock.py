import threading

from src.queue import queue as q
from src.queue.queue import enqueue_task, get_queue
from src.types import SourceType
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    q._paused = True
    q._in_flight.clear()


def test_concurrent_enqueue_preserves_unique_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    q._queue.clear()
    errors = []

    def fire():
        try:
            for i in range(50):
                enqueue_task(f"t{i}", SourceType.FILE, f"hash-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len({task.id for task in get_queue()}) == 50


def test_process_next_does_not_select_task_already_in_flight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    q._queue.clear()
    task_id = enqueue_task("t1", SourceType.FILE, "hash-1")
    q._in_flight.add(task_id)
    q._paused = False
    emitted = []
    monkeypatch.setattr(q.event_bus, "emit", lambda *args: emitted.append(args))

    q._process_next()

    assert not emitted
    assert get_queue()[0].status is q.TaskStatus.PENDING
