"""Verify the service-level lock invariant under concurrent enqueue.

The legacy queue.py used a module-global threading.Lock; the refactored
QueueService uses per-instance threading.Lock. The invariant under test:
8 threads × 50 enqueue attempts over 50 distinct task hashes must produce
exactly 50 unique task IDs — the shared hashes deduplicate under the
lock, and no attempt is lost or double-inserted.

The service is constructed directly with in-memory fakes and a no-op
event emitter, so the test exercises only the queue's lock/dedup
invariant and never triggers the pipeline's global "collector:start"
handler (which, via the process-wide PipelineService singleton, would
run the real pipeline and hang on a cross-loop asyncio.Semaphore).
"""
import threading

from src.queue.service import QueueService
from src.queue.retry import DefaultRetryPolicy
from src.types import SourceType
from .conftest import FakeQueueBackend, FakeEventEmitter


def test_concurrent_enqueue_preserves_unique_tasks(fake_backend, fake_tracker, fake_emitter):
    service = QueueService(
        backend=fake_backend,
        tracker=fake_tracker,
        emitter=fake_emitter,
        retry_policy=DefaultRetryPolicy(),
    )
    errors = []

    def fire():
        try:
            for i in range(50):
                service.enqueue(f"t{i}", SourceType.FILE, f"hash-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=fire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len({task.id for task in service.get_queue()}) == 50
