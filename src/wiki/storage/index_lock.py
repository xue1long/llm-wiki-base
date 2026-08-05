"""Thread-safe index.md updates.

Provides mutual exclusion for index.md writes to prevent
race conditions when multiple tasks update the index concurrently.

Usage:
    from src.wiki.storage.index_lock import with_index_lock

    @with_index_lock
    def update_index(page: WikiPage, paths: WikiPaths):
        append_to_index(page, paths)
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from functools import wraps
from typing import TYPE_CHECKING, Generator, Callable, TypeVar, ParamSpec

if TYPE_CHECKING:
    from pathlib import Path
    from ..core.types import WikiPage
    from ..core.paths import WikiPaths

logger = logging.getLogger(__name__)

# Module-level lock for index.md writes
# Use RLock (reentrant lock) so same thread can acquire multiple times
# This is important for nested operations that both need the lock
_index_lock = threading.RLock()

# Track lock statistics for monitoring
_lock_stats = {
    "acquires": 0,
    "releases": 0,
    "contentions": 0,  # Times had to wait for lock
}


@contextmanager
def index_lock() -> Generator[None, None, None]:
    """Acquire the index.md lock for the duration of the context.

    Example:
        with index_lock():
            append_to_index(page, paths)
    """
    # Try to acquire without blocking first
    acquired = _index_lock.acquire(blocking=False)

    if acquired:
        _lock_stats["acquires"] += 1
    else:
        # Had to wait - log contention
        _lock_stats["contentions"] += 1
        logger.debug("[IndexLock] Contention detected, waiting...")
        _index_lock.acquire(blocking=True)
        _lock_stats["acquires"] += 1

    try:
        yield
    finally:
        _index_lock.release()
        _lock_stats["releases"] += 1


def with_index_lock(func: Callable) -> Callable:
    """Decorator to wrap a function with index lock.

    Example:
        @with_index_lock
        def append_to_index(page: WikiPage, paths: WikiPaths):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with index_lock():
            return func(*args, **kwargs)
    return wrapper


def safe_append_to_index(page: "WikiPage", paths: "WikiPaths") -> None:
    """Thread-safe append to index.md.

    This is the recommended entry point for appending to index.md.
    It acquires the index lock before writing to prevent race conditions.

    Args:
        page: WikiPage to append
        paths: WikiPaths for the project
    """
    from .page_writer import append_to_index

    with index_lock():
        append_to_index(page, paths)


def safe_write_index_entry(
    index_path: "Path",
    page_id: str,
    page_type: str,
    title: str,
) -> None:
    """Thread-safe write of a single index entry.

    Args:
        index_path: Path to index.md
        page_id: Page ID
        page_type: Page type (source, entity, concept, synthesis)
        title: Page title
    """
    with index_lock():
        entry = f"- **{page_id}** ({page_type}) — {title}\n"
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(entry)


def get_lock_stats() -> dict:
    """Get lock statistics for monitoring.

    Returns:
        Dict with keys: acquires, releases, contentions
    """
    return _lock_stats.copy()


def reset_lock_stats() -> None:
    """Reset lock statistics (for testing)."""
    global _lock_stats
    _lock_stats = {
        "acquires": 0,
        "releases": 0,
        "contentions": 0,
    }


# Re-export for convenience
__all__ = [
    "index_lock",
    "with_index_lock",
    "safe_append_to_index",
    "safe_write_index_entry",
    "get_lock_stats",
    "reset_lock_stats",
]