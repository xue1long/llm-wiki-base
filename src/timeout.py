# ruflo-kb/src/timeout.py
"""
任务超时控制

- 任务执行超时检测
- 超时后自动终止并标记
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable, Any
from functools import wraps

logger = logging.getLogger(__name__)

class TaskTimeoutError(Exception):
    """任务超时异常"""
    def __init__(self, task_id: str, timeout_seconds: int):
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Task {task_id} timed out after {timeout_seconds} seconds")

@dataclass
class TaskTimeoutConfig:
    collector_timeout: int = 300     # 5分钟
    processor_timeout: int = 300    # 5分钟
    librarian_timeout: int = 300   # 5分钟
    default_timeout: int = 60       # 默认1分钟

def with_timeout(
    timeout_seconds: int,
    task_id: Optional[str] = None,
):
    """
    超时装饰器

    用法:
    @with_timeout(30, task_id="task-123")
    async def my_operation():
        ...
    """
    def decorator(func: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.warning(f"[Timeout] Task {task_id} exceeded {timeout_seconds}s")
                raise TaskTimeoutError(task_id or "unknown", timeout_seconds)

        return wrapper

    return decorator

async def run_with_timeout(
    coro: Awaitable,
    timeout_seconds: int,
    task_id: str,
) -> Any:
    """
    运行协程，带超时控制

    Args:
        coro: 协程
        timeout_seconds: 超时秒数
        task_id: 任务ID（用于日志）

    Returns:
        协程结果

    Raises:
        TaskTimeoutError: 超时时抛出
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"[Timeout] Task {task_id} exceeded {timeout_seconds}s")
        raise TaskTimeoutError(task_id, timeout_seconds)

class TimeoutTracker:
    """超时追踪器"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._timeouts: dict[str, datetime] = {}

    def start(self, task_id: str, coro: Awaitable, timeout_seconds: int) -> asyncio.Task:
        """启动带超时的任务"""
        async def tracked():
            try:
                return await asyncio.wait_for(coro, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(f"[TimeoutTracker] Task {task_id} timed out")
                raise TaskTimeoutError(task_id, timeout_seconds)

        task = asyncio.create_task(tracked())
        self._tasks[task_id] = task
        self._timeouts[task_id] = datetime.now() + timedelta(seconds=timeout_seconds)
        return task

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            del self._tasks[task_id]
            del self._timeouts[task_id]
            return True
        return False

    def is_timed_out(self, task_id: str) -> bool:
        """检查任务是否超时"""
        if task_id not in self._timeouts:
            return False
        return datetime.now() > self._timeouts[task_id]

    def get_pending(self) -> list[str]:
        """获取待处理任务ID列表"""
        return list(self._tasks.keys())

# 全局超时追踪器
_timeout_tracker = TimeoutTracker()

def get_timeout_tracker() -> TimeoutTracker:
    """获取全局超时追踪器"""
    return _timeout_tracker
