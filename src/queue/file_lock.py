"""File-level lock manager for parallel processing within same project.

Allows concurrent processing of different files in the same project
while maintaining thread safety for shared resources like index.md.

Configuration:
    RUFLO_MAX_PROJECT_CONCURRENCY: Max concurrent files per project (default: 4)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections import defaultdict
from typing import Dict, Set

logger = logging.getLogger(__name__)

# Default: 4 concurrent files per project
DEFAULT_MAX_PROJECT_CONCURRENCY = 4


class FileLockManager:
    """Manages file-level locks for parallel processing.

    Allows same-project different-file parallelism with a per-project
    concurrency limit. Same file operations are serialized.

    Example:
        manager = FileLockManager()
        await manager.acquire("project-1", "raw/sources/file1.md")
        # ... process file ...
        manager.release("project-1", "raw/sources/file1.md")
    """

    def __init__(self, max_per_project: int | None = None):
        """Initialize the lock manager.

        Args:
            max_per_project: Maximum concurrent files per project.
                Default: RUFLO_MAX_PROJECT_CONCURRENCY env var or 4.
        """
        self._max_per_project = max_per_project or int(
            os.environ.get("RUFLO_MAX_PROJECT_CONCURRENCY", str(DEFAULT_MAX_PROJECT_CONCURRENCY))
        )

        # File-level locks: {file_key: threading.Lock}
        self._file_locks: Dict[str, threading.Lock] = {}
        self._file_locks_mutex = threading.Lock()

        # Project-level semaphores: {project_id: threading.Semaphore}
        # Use threading.Semaphore (not asyncio.Semaphore) because:
        # 1. PipelineService runs in async context but file_lock_manager.acquire()
        #    may be called from different threads with different event loops
        # 2. threading.Semaphore works across threads, asyncio.Semaphore does not
        self._project_semaphores: Dict[str, threading.Semaphore] = {}
        self._semaphores_mutex = threading.Lock()

        # Track which files are currently locked
        self._locked_files: Dict[str, Set[str]] = defaultdict(set)
        self._locked_files_mutex = threading.Lock()

        # Statistics
        self._stats = {
            "acquires": 0,
            "releases": 0,
            "contentions": 0,
            "project_waits": 0,
        }

    def _get_file_lock(self, file_key: str) -> threading.Lock:
        """Get or create a lock for a specific file."""
        with self._file_locks_mutex:
            if file_key not in self._file_locks:
                self._file_locks[file_key] = threading.Lock()
            return self._file_locks[file_key]

    def _get_project_semaphore(self, project_id: str) -> threading.Semaphore:
        """Get or create a threading.Semaphore for a project."""
        with self._semaphores_mutex:
            if project_id not in self._project_semaphores:
                self._project_semaphores[project_id] = threading.Semaphore(
                    self._max_per_project
                )
            return self._project_semaphores[project_id]

    async def acquire(
        self,
        project_id: str,
        source: str,
        timeout: float = 300.0,
    ) -> bool:
        """Acquire lock for processing a file.

        Flow:
        1. Wait for project semaphore slot (max N concurrent files)
        2. Acquire file-level lock (serialize same-file operations)

        Args:
            project_id: Project identifier
            source: File path or URL
            timeout: Maximum wait time in seconds

        Returns:
            True if lock acquired, False if timeout

        Raises:
            TimeoutError: If cannot acquire within timeout
        """
        file_key = f"{project_id}:{source}"

        # Step 1: Acquire project semaphore (threading.Semaphore, run in thread)
        semaphore = self._get_project_semaphore(project_id)

        def acquire_semaphore():
            return semaphore.acquire(blocking=True, timeout=timeout)

        try:
            # Run blocking semaphore acquire in thread pool
            acquired = await asyncio.get_event_loop().run_in_executor(
                None, acquire_semaphore
            )
            if not acquired:
                raise TimeoutError(
                    f"Could not acquire project slot within {timeout}s "
                    f"(project: {project_id}, max: {self._max_per_project})"
                )
        except Exception:
            self._stats["project_waits"] += 1
            logger.warning(
                "[FileLock] Project %s semaphore timeout (max %d concurrent)",
                project_id, self._max_per_project
            )
            raise TimeoutError(
                f"Could not acquire project slot within {timeout}s "
                f"(project: {project_id}, max: {self._max_per_project})"
            )

        # Step 2: Acquire file lock (sync, but should be fast)
        file_lock = self._get_file_lock(file_key)

        acquired = file_lock.acquire(blocking=False)
        if not acquired:
            # Had to wait for file lock
            self._stats["contentions"] += 1
            logger.debug(
                "[FileLock] File contention: %s, waiting...",
                source[:50]
            )
            file_lock.acquire(blocking=True)

        # Track locked file
        with self._locked_files_mutex:
            self._locked_files[project_id].add(file_key)

        self._stats["acquires"] += 1
        logger.debug(
            "[FileLock] Acquired: project=%s file=%s",
            project_id, source[:50]
        )

        return True

    def release(self, project_id: str, source: str) -> None:
        """Release lock for a file.

        Must be called after acquire() when processing is complete.

        Args:
            project_id: Project identifier
            source: File path or URL
        """
        file_key = f"{project_id}:{source}"

        # Release file lock
        file_lock = self._get_file_lock(file_key)
        try:
            file_lock.release()
        except RuntimeError:
            # Lock was not held (shouldn't happen in correct usage)
            logger.warning("[FileLock] Attempted to release unlocked file: %s", source)
            return

        # Release project semaphore
        semaphore = self._get_project_semaphore(project_id)
        semaphore.release()

        # Untrack locked file
        with self._locked_files_mutex:
            self._locked_files[project_id].discard(file_key)

        self._stats["releases"] += 1
        logger.debug(
            "[FileLock] Released: project=%s file=%s",
            project_id, source[:50]
        )

    def get_locked_files(self, project_id: str) -> Set[str]:
        """Get set of currently locked files for a project."""
        with self._locked_files_mutex:
            return set(self._locked_files.get(project_id, set()))

    def get_stats(self) -> dict:
        """Get lock statistics."""
        return self._stats.copy()


# Module-level singleton
_manager: FileLockManager | None = None


def get_file_lock_manager() -> FileLockManager:
    """Get or create the singleton FileLockManager."""
    global _manager
    if _manager is None:
        _manager = FileLockManager()
    return _manager


def reset_file_lock_manager() -> None:
    """Reset the singleton (for testing)."""
    global _manager
    _manager = None