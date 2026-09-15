"""Soft PID lock for the v7 reviews queue (O1 加固).

Background:
- The v7 pipeline reads/writes `.index/reviews_queue.json` from a single
  `extract_full.py` invocation. Multiple concurrent processes targeting
  the same project root can interleave writes and corrupt the queue.
- A real flock(2) is not portable to Windows + we explicitly want to
  avoid OS-level locks (personal-use scope).
- This module provides a *best-effort* PID lock as a soft warning:
  - ``acquire_queue_lock(root)`` tries to create `.index/.queue-lock`
    with O_CREAT|O_EXCL; on success the lock holds until release.
  - On contention it returns ``False`` and the caller aborts with
    "another process is writing the queue".

Caveats (documented):
- PID-based locks are unreliable: stale `.queue-lock` from a crashed
  process will block new acquisitions until manually removed.
- Crash-safe cleanup is partial: ``atexit`` hook in extract_full.py
  releases on graceful exit; SIGKILL/SIGSEGV leaves the lock behind.
- Multi-process concurrent ingestion is NOT supported; the lock is a
  hint to abort early, not a correctness guarantee.

For true multi-process safety, upgrade to file-locking (msvcrt /
fcntl) or move the queue to a database (out of scope for this plan).
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path

_LOCK_FILENAME = ".queue-lock"


def _lock_path(root: Path) -> Path:
    return Path(root) / ".index" / _LOCK_FILENAME


def acquire_queue_lock(root: Path) -> bool:
    """Try to acquire the queue lock for ``root``.

    Returns ``True`` if the lock was acquired (caller must release it),
    or ``False`` if another process already holds it.
    """
    path = _lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def release_queue_lock(root: Path) -> None:
    """Release the queue lock for ``root``.

    Safe to call even if the lock is not held (no-op).
    """
    _lock_path(root).unlink(missing_ok=True)


def install_atexit_release(root: Path) -> None:
    """Register an atexit hook to release the lock on graceful exit.

    Note: atexit does NOT run on SIGKILL / os._exit / unhandled
    exceptions in C extensions. Use with caution.
    """
    atexit.register(release_queue_lock, root)


def is_lock_held(root: Path) -> bool:
    """Return True if a lock file currently exists for ``root``."""
    return _lock_path(root).exists()


def read_lock_pid(root: Path) -> int | None:
    """Return the PID stored in the lock file, or None if unreadable."""
    path = _lock_path(root)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
