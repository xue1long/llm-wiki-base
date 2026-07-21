"""Per-project async mutex + sync wrapper.

Different project_ids are fully concurrent. Same project_id is serialized.
Single-process assumption (v1).
"""
import asyncio
from typing import Awaitable, Callable, TypeVar


T = TypeVar("T")

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(project_id: str) -> asyncio.Lock:
    """Get-or-create lock for project_id."""
    if project_id not in _locks:
        _locks[project_id] = asyncio.Lock()
    return _locks[project_id]


async def with_project_lock(project_id: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Serialize mutations within a project. Async context.

    Usage:
        result = await with_project_lock("uuid-123", some_async_fn)

    Different project_ids run concurrently; same project_id is serialized.
    """
    async with _lock_for(project_id):
        return await fn()


def sync_with_project_lock(project_id: str, fn: Callable[[], T]) -> T:
    """Sync wrapper for CLI subcommands. Blocks until lock acquired + fn done.

    Usage:
        result = sync_with_project_lock("uuid-123", lambda: do_work())

    Internally uses asyncio.run; can NOT be called from within an async context.
    """
    async def _wrapper() -> T:
        async with _lock_for(project_id):
            return fn()

    # asyncio.run() creates new event loop
    return asyncio.run(_wrapper())


def __reset_for_testing() -> None:
    """Drop all live locks. Test-only."""
    _locks.clear()
