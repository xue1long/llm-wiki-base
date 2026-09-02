"""Public queue subsystem API.

All public functions are thin wrappers over QueueService. The legacy
src/queue/queue.py is gone — it was migrated to:
- state.py       (state machine)
- ports.py       (Protocols)
- in_flight.py   (InMemoryInFlightTracker)
- persistence.py (JsonFileBackend)
- retry.py       (DefaultRetryPolicy)
- scheduler.py   (select_next_task)
- service.py     (QueueService composition root + module-level helpers)
"""
from .service import (
    QueueService,
    __reset_for_testing,
    generate_task_id,
    get_default_queue_service,
)
from .state import InvalidTransition

# Module-level convenience functions that delegate to the default service.
# Each holds a reference to the singleton, not the function, so tests that
# rebuild the singleton via __reset_for_testing see the new instance.


def _service():
    return get_default_queue_service()


def enqueue_task(source, source_type, task_hash, project_id=None,
                 folder_context=None, batch_id=None, ingest_snapshot=None):
    return _service().enqueue(source, source_type, task_hash,
                              project_id=project_id,
                              folder_context=folder_context,
                              batch_id=batch_id,
                              ingest_snapshot=ingest_snapshot)


def enqueue_batch(items, project_id=None, folder_context=None, batch_id=None):
    return _service().enqueue_batch(items, project_id=project_id,
                                    folder_context=folder_context,
                                    batch_id=batch_id)


def update_task_status(task_id, status, error=None):
    return _service().update_status(task_id, status, error=error)


def get_queue():
    return _service().get_queue()


def pause_queue():
    return _service().pause()


def resume_queue():
    return _service().resume()


__all__ = [
    "QueueService",
    "InvalidTransition",
    "enqueue_task",
    "update_task_status",
    "get_queue",
    "pause_queue",
    "resume_queue",
    "generate_task_id",
    "get_default_queue_service",
    "__reset_for_testing",
]
