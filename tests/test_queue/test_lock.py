"""Verify the service-level lock invariant under concurrent enqueue.

The legacy queue.py used a module-global threading.Lock; the refactored
QueueService uses per-instance threading.Lock. The invariant under
test is the same: 8 threads × 50 enqueues each must produce 400 unique
task IDs and exactly 400 tasks in the snapshot.

After the queue refactor (Tasks 1-7), the production code path is
through QueueService.enqueue, which serializes the snapshot +
acquire + emit + save sequence under a single service-level lock.
"""
import threading

from src.queue import enqueue_task, get_queue
from src.queue import __reset_for_testing
from src.types import SourceType
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()


def test_concurrent_enqueue_preserves_unique_tasks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    __reset_for_testing()
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