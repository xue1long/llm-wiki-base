# ruflo-kb/src/queue/queue.py
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..events.event_bus import event_bus
from ..events.events import EventName, TaskCreatedPayload, TaskStatusChangedPayload
from ..types import KnowledgeTask, TaskStatus, SourceType
from ..utils.idempotency import check_duplicate

logger = logging.getLogger(__name__)

QUEUE_FILE = ".kb-queue.json"
MAX_RETRIES = 3

_queue: list[KnowledgeTask] = []
_processing = False
_paused = False

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
    """更新任务状态"""
    global _queue

    task = next((t for t in _queue if t.id == task_id), None)
    if not task:
        return

    prev_status = task.status
    task.status = status
    task.updated_at = int(datetime.now().timestamp())

    if error:
        task.error = error

    if status == TaskStatus.FAILED:
        task.retry_count += 1
        if task.retry_count < MAX_RETRIES:
            task.status = TaskStatus.PENDING  # 自动重试

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
    global _paused
    _paused = True

def resume_queue() -> None:
    global _paused
    _paused = False
    _process_next()

def _save_queue() -> None:
    try:
        pending = [t for t in _queue if t.status != TaskStatus.APPROVED]
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump([vars(t) for t in pending], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[Queue] Failed to save: {e}")

def _load_queue() -> None:
    global _queue
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _queue = [KnowledgeTask(**t) for t in data]
    except FileNotFoundError:
        _queue = []

def _process_next() -> None:
    global _processing, _paused, _queue

    if _processing or _paused:
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
