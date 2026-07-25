# ruflo-kb/src/queue/queue.py
import json
import logging
import threading
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..events.event_bus import event_bus
from ..events.events import EventName, TaskCreatedPayload, TaskStatusChangedPayload
from ..lib.write_hooks import safe_write
from ..types import KnowledgeTask, TaskStatus, SourceType
from ..utils.idempotency import check_duplicate
from ..circuit_breaker import get_circuit_breaker, CircuitState
# Soft-migrated (Task 1): state machine now lives in src/queue/state.py.
# Re-export InvalidTransition so existing `from src.queue.queue import
# InvalidTransition` callers (e.g. tests/test_queue/test_update_task_status_transitions.py)
# keep working without changes.
from .state import InvalidTransition, can_transition

logger = logging.getLogger(__name__)

QUEUE_FILE = ".kb-queue.json"
MAX_RETRIES = 3
CIRCUIT_BREAKER_NAME = "task_queue"

_queue: list[KnowledgeTask] = []
_lock = threading.Lock()
_in_flight: set[str] = set()
_paused = False


def _default_state() -> dict:
    """Default in-memory queue state snapshot (read-only contract for ingest API)."""
    with _lock:
        return {
            "paused": _paused,
            "pending": len([t for t in _queue if t.status == TaskStatus.PENDING]),
            "running": len([t for t in _queue if t.status == TaskStatus.RUNNING]),
            "failed": len([t for t in _queue if t.status == TaskStatus.FAILED]),
        }


def generate_task_id() -> str:
    unique_part = uuid.uuid4().hex[:8]
    return f"kb-{datetime.now().strftime('%Y%m%d%H%M%S')}-{unique_part}"

def enqueue_task(source: str, source_type: SourceType, task_hash: str,
                project_id: str | None = None) -> str:
    """
    入队新任务
    返回 task_id，若重复则返回空字符串

    Audit I5: ``project_id`` is threaded through into the
    ``collector:start`` payload so the pipeline resolves the correct
    project's WikiPaths rather than the CWD-relative ``Knowledge/`` default.
    """
    with _lock:
        if check_duplicate(task_hash):
            logger.info(f"[Queue] Duplicate task_hash: {task_hash}")
            return ""

        task = KnowledgeTask(
            id=generate_task_id(),
            source=source,
            source_type=source_type,
            status=TaskStatus.PENDING,
            task_hash=task_hash,
            created_at=int(datetime.now().timestamp()),
            updated_at=int(datetime.now().timestamp()),
            retry_count=0,
            project_id=project_id,
        )
        _queue.append(task)
        _save_queue_unlocked()

    # Event handlers may update the queue, so never emit while holding _lock.
    event_bus.emit(EventName.TASK_CREATED, TaskCreatedPayload(
        task_id=task.id,
        source=task.source,
        source_type=task.source_type,
        task_hash=task.task_hash,
        project_id=project_id,
    ))
    _process_next(task_id=task.id, project_id=project_id)
    return task.id

def update_task_status(task_id: str, status: TaskStatus, error: Optional[str] = None) -> None:
    """Update a task after validating the state-machine transition."""
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)

    with _lock:
        task = next((t for t in _queue if t.id == task_id), None)
        if task is None:
            raise KeyError(task_id)

        prev_status = TaskStatus(task.status)
        if not can_transition(prev_status, status):
            raise InvalidTransition(task_id, prev_status.value, status.value)

        task.status = status
        task.updated_at = int(datetime.now().timestamp())

        if error is not None:
            task.error = error

        emit_status = status
        retry_will_resume = False
        dead_letter_payload: dict | None = None

        if status == TaskStatus.FAILED:
            task.retry_count += 1
            breaker.record_failure()

            if task.retry_count >= MAX_RETRIES:
                # Retry exhaustion: flip to DEAD_LETTER, emit dead-letter
                # event with diagnostic payload, and pause the queue if the
                # circuit breaker has tripped.
                task.status = TaskStatus.DEAD_LETTER
                emit_status = TaskStatus.DEAD_LETTER
                last_error = task.error or error or ""
                dead_letter_payload = {
                    "task_id": task_id,
                    "retry_count": task.retry_count,
                    "last_error": last_error,
                }
                logger.warning(
                    f"[Queue] Task {task_id} exceeded max retries, moving to dead letter"
                )

                # 触发熔断检查
                if breaker.state == CircuitState.OPEN:
                    logger.error(
                        f"[Queue] Circuit breaker OPEN - queue paused due to repeated failures"
                    )
                    _pause_queue_unlocked()
            else:
                task.status = TaskStatus.PENDING  # 自动重试
                emit_status = TaskStatus.PENDING
                retry_will_resume = True
        elif status == TaskStatus.ARCHIVED:
            breaker.record_success()
        elif status == TaskStatus.TIMEOUT:
            breaker.record_failure()
            if task.retry_count + 1 >= MAX_RETRIES:
                task.status = TaskStatus.DEAD_LETTER
                emit_status = TaskStatus.DEAD_LETTER
                dead_letter_payload = {
                    "task_id": task_id,
                    "retry_count": task.retry_count + 1,
                    "last_error": task.error or error or "",
                }
                logger.warning(
                    f"[Queue] Task {task_id} timed out beyond max retries, moving to dead letter"
                )
                if breaker.state == CircuitState.OPEN:
                    logger.error(
                        f"[Queue] Circuit breaker OPEN - queue paused due to repeated failures"
                    )
                    _pause_queue_unlocked()

        # Capture the payload under the lock and release before emitting; the
        # lock is a non-reentrant threading.Lock and any handler that calls
        # back into the queue would deadlock.
        emit_payload = TaskStatusChangedPayload(
            task_id=task_id,
            from_status=prev_status,
            to_status=emit_status,
            error=error,
        )

        _save_queue_unlocked()

    # Outside the lock: notify subscribers, then advance the queue so a
    # retry / new pending task is picked up without waiting for the next
    # enqueue / resume.
    event_bus.emit(EventName.TASK_STATUS_CHANGED, emit_payload)
    if dead_letter_payload is not None:
        event_bus.emit(EventName.TASK_DEAD_LETTER, dead_letter_payload)
    if retry_will_resume:
        _process_next()

def get_queue() -> list[KnowledgeTask]:
    with _lock:
        return _queue.copy()

def _pause_queue_unlocked() -> None:
    global _paused
    _paused = True
    logger.warning("[Queue] Queue paused")

def pause_queue() -> None:
    """暂停队列处理"""
    with _lock:
        _pause_queue_unlocked()

def resume_queue() -> None:
    """恢复队列处理"""
    global _paused
    with _lock:
        _paused = False
        breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
        breaker.record_success()  # 尝试恢复
        logger.info("[Queue] Queue resumed")
    _process_next()

def get_queue_status() -> dict:
    """获取队列状态"""
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
    with _lock:
        return {
            "paused": _paused,
            "circuit_breaker_state": breaker.state.value,
            "failure_count": breaker.failure_count,
            "pending_count": len([t for t in _queue if t.status == TaskStatus.PENDING]),
            "running_count": len([t for t in _queue if t.status == TaskStatus.RUNNING]),
            "failed_count": len([t for t in _queue if t.status == TaskStatus.FAILED]),
        }

def _save_queue() -> None:
    """Persist queue to disk. Self-locking; safe to call without holding the lock."""
    with _lock:
        _save_queue_unlocked()


def _save_queue_unlocked() -> None:
    """Persist queue to disk; callers hold the queue mutex."""
    try:
        pending = [t for t in _queue if t.status != TaskStatus.APPROVED]
        payload = json.dumps([vars(t) for t in pending], ensure_ascii=False, indent=2)
        safe_write(QUEUE_FILE, payload)
    except Exception as e:
        logger.error(f"[Queue] Failed to save: {e}")


def _load_queue() -> None:
    """Load queue from disk. Self-locking; safe to call without holding the lock.

    On any existing-but-corrupt file, log a warning and start with an empty
    queue rather than raising. Missing file → empty queue (no warning).
    """
    global _queue
    with _lock:
        _load_queue_unlocked()


def _load_queue_unlocked() -> None:
    """Load queue from disk; callers hold the queue mutex.

    On any existing-but-corrupt file, log a warning and start with an empty
    queue rather than raising. Missing file → empty queue (no warning).
    """
    global _queue
    _queue = []
    queue_path = Path(QUEUE_FILE)
    if not queue_path.exists():
        return
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[Queue] queue file corrupt ({e}); starting with empty queue")
        return
    if not isinstance(data, list):
        logger.warning("[Queue] queue file did not contain a list; starting with empty queue")
        return
    try:
        _queue = [KnowledgeTask(**row) for row in data]
    except (TypeError, ValueError) as e:
        logger.warning(f"[Queue] queue file rows malformed ({e}); starting with empty queue")
        _queue = []


def __reset_for_testing() -> None:
    """Test-only: re-load the queue from disk and clear in-flight tracking."""
    with _lock:
        _load_queue_unlocked()
        _in_flight.clear()


def release_in_flight(task_id: str) -> None:
    """Release a task after its collector pipeline reaches a terminal state.

    After dropping the in-flight flag, kick the scheduler so any backlog (e.g.
    tasks queued while paused, or a retry that was reset to PENDING) advances
    without waiting for the next enqueue / resume.
    """
    with _lock:
        _in_flight.discard(task_id)
    _process_next()


def _process_next(task_id: str | None = None, project_id: str | None = None) -> None:
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
    with _lock:
        if _paused:
            return
        if not breaker.can_execute():
            logger.warning(f"[Queue] Circuit breaker is {breaker.state.value}, skipping processing")
            return

        if task_id is not None:
            # Explicit dispatch path (audit I5): enqueue_task triggers
            # _process_next(task_id, project_id) so the freshly enqueued task
            # is picked up immediately with the originating project_id
            # threaded through.
            task = next((t for t in _queue if t.id == task_id), None)
            if task is None or task.id in _in_flight or task.status != TaskStatus.PENDING:
                return
            _in_flight.add(task.id)
            source = task.source
            source_type = task.source_type
            # Prefer the caller-supplied project_id, fall back to the task's
            # own project_id if present.
            effective_project_id = project_id or task.project_id
        else:
            task = next(
                (candidate for candidate in _queue
                 if candidate.status == TaskStatus.PENDING
                 and candidate.id not in _in_flight),
                None,
            )
            if task is None:
                return
            _in_flight.add(task.id)
            task_id = task.id
            source = task.source
            source_type = task.source_type
            effective_project_id = task.project_id

    # The collector chain owns the RUNNING transition and clears _in_flight
    # when collector:done finishes. Release the lock before emitting.
    payload = {
        "task_id": task_id,
        "source": source,
        "source_type": source_type,
    }
    if effective_project_id is not None:
        payload["project_id"] = effective_project_id
    event_bus.emit("collector:start", payload)

# 启动时加载队列（_load_queue 自带锁）
_load_queue()
