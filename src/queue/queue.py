# ruflo-kb/src/queue/queue.py
import json
import logging
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

logger = logging.getLogger(__name__)

QUEUE_FILE = ".kb-queue.json"
MAX_RETRIES = 3
CIRCUIT_BREAKER_NAME = "task_queue"

_queue: list[KnowledgeTask] = []
_processing = False
_paused = False


class InvalidTransition(Exception):
    """Raised when a task status change violates the state machine."""

    def __init__(self, task_id: str, prev_status: str, next_status: str):
        super().__init__(task_id, prev_status, next_status)
        self.task_id = task_id
        self.prev_status = prev_status
        self.next_status = next_status


def _default_state() -> dict:
    """Default in-memory queue state snapshot (read-only contract for ingest API)."""
    return {
        "paused": _paused,
        "pending": len([t for t in _queue if t.status == TaskStatus.PENDING]),
        "running": len([t for t in _queue if t.status == TaskStatus.RUNNING]),
        "failed": len([t for t in _queue if t.status == TaskStatus.FAILED]),
    }

def generate_task_id() -> str:
    unique_part = uuid.uuid4().hex[:8]
    return f"kb-{datetime.now().strftime('%Y%m%d%H%M%S')}-{unique_part}"

def enqueue_task(source: str, source_type: SourceType, task_hash: str) -> str:
    """
    入队新任务
    返回 task_id，若重复则返回空字符串
    """
    global _queue

    # 检查重复
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
    )

    _queue.append(task)
    _save_queue()

    event_bus.emit(EventName.TASK_CREATED, TaskCreatedPayload(
        task_id=task.id,
        source=task.source,
        source_type=task.source_type,
        task_hash=task.task_hash,
    ))

    _process_next()
    return task.id

def update_task_status(task_id: str, status: TaskStatus, error: Optional[str] = None) -> None:
    """Update a task after validating the state-machine transition."""
    global _queue
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)

    task = next((t for t in _queue if t.id == task_id), None)
    if task is None:
        raise KeyError(task_id)

    from ..orchestrator.state_machine import can_transition

    prev_status = TaskStatus(task.status)
    if not can_transition(prev_status, status):
        raise InvalidTransition(task_id, prev_status.value, status.value)

    task.status = status
    task.updated_at = int(datetime.now().timestamp())

    if error is not None:
        task.error = error

    if status == TaskStatus.FAILED:
        task.retry_count += 1
        breaker.record_failure()

        if task.retry_count >= MAX_RETRIES:
            # 达到最大重试次数，标记为需要人工介入
            task.status = TaskStatus.FAILED
            logger.warning(f"[Queue] Task {task_id} exceeded max retries, moving to dead letter")

            # 触发熔断检查
            if breaker.state == CircuitState.OPEN:
                logger.error(f"[Queue] Circuit breaker OPEN - queue paused due to repeated failures")
                pause_queue()
        else:
            task.status = TaskStatus.PENDING  # 自动重试
    elif status == TaskStatus.ARCHIVED:
        breaker.record_success()
    elif status == TaskStatus.TIMEOUT:
        breaker.record_failure()

    event_bus.emit(EventName.TASK_STATUS_CHANGED, TaskStatusChangedPayload(
        task_id=task_id,
        from_status=prev_status,
        to_status=status,
        error=error,
    ))

    _save_queue()

def get_queue() -> list[KnowledgeTask]:
    return _queue.copy()

def pause_queue() -> None:
    """暂停队列处理"""
    global _paused
    _paused = True
    logger.warning("[Queue] Queue paused")

def resume_queue() -> None:
    """恢复队列处理"""
    global _paused
    _paused = False
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
    breaker.record_success()  # 尝试恢复
    logger.info("[Queue] Queue resumed")
    _process_next()

def get_queue_status() -> dict:
    """获取队列状态"""
    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
    return {
        "paused": _paused,
        "circuit_breaker_state": breaker.state.value,
        "failure_count": breaker.failure_count,
        "pending_count": len([t for t in _queue if t.status == TaskStatus.PENDING]),
        "running_count": len([t for t in _queue if t.status == TaskStatus.RUNNING]),
        "failed_count": len([t for t in _queue if t.status == TaskStatus.FAILED]),
    }

def _save_queue() -> None:
    """Persist queue to disk via safe_write (atomic tmp+replace when not suspended)."""
    try:
        pending = [t for t in _queue if t.status != TaskStatus.APPROVED]
        payload = json.dumps([vars(t) for t in pending], ensure_ascii=False, indent=2)
        safe_write(QUEUE_FILE, payload)
    except Exception as e:
        logger.error(f"[Queue] Failed to save: {e}")


def _load_queue() -> None:
    """Load queue from disk; recover from JSONDecodeError / OSError (empty list).

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
    """Test-only: re-load the queue from disk.

    Used by tests that mutate the on-disk queue file directly and need a
    fresh in-memory state to mirror it. Production code never calls this.
    """
    _load_queue()

def _process_next() -> None:
    global _processing, _paused, _queue

    if _processing or _paused:
        return

    breaker = get_circuit_breaker(CIRCUIT_BREAKER_NAME)
    if not breaker.can_execute():
        logger.warning(f"[Queue] Circuit breaker is {breaker.state.value}, skipping processing")
        return

    task = next((t for t in _queue if t.status == TaskStatus.PENDING), None)
    if not task:
        return

    _processing = True
    task.status = TaskStatus.RUNNING
    task.updated_at = int(datetime.now().timestamp())
    _save_queue()

    event_bus.emit("collector:start", {
        "task_id": task.id,
        "source": task.source,
        "source_type": task.source_type,
    })

    _processing = False

# 启动时加载队列
_load_queue()
