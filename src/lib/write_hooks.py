"""safe_write hook — respects AtomicContext to batch writes.

When NOT inside an AtomicContext, safe_write uses an atomic write pattern
(write to *.tmp then os.replace) so a crash mid-write never produces a torn
target file. This matches the pattern used in src/project/registry.py:89-101.

Inside an AtomicContext, writes are buffered into a per-thread bucket and
only flushed at the atomic commit point (see flush_pending_writes /
AtomicContext). The DELETE_SENTINEL marker queues a deferred deletion,
executed at flush time.

Thread safety: AtomicContext's suspend flag is per-thread (threading.local),
so each thread has its own suspended state. The pending-writes buffer is
keyed by `threading.get_ident()` so concurrent AtomicContext instances in
different threads never overwrite each other's writes; on exit the exiting
thread flushes only its own bucket.
"""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Union

from .atomic_ctx import is_suspended


_logger = logging.getLogger(__name__)


DELETE_SENTINEL = "__WIKI_DELETE__"
# Per-thread buckets of pending writes. Each thread owns its bucket; only
# that thread reads/writes to it during normal flow. AtomicContext.__exit__
# flushes and clears only the exiting thread's bucket.
_pending_writes_by_thread: dict[int, dict[Path, str]] = {}


class AtomicCommitError(Exception):
    """Raised when flushing a batched atomic write partially fails (R3).

    Carries ``failed_paths`` (the exact paths whose flush failed) so the
    caller can surface them, mark the task FAILED, and drive a retry. A
    raise here replaces the old "log and continue" behaviour that let
    partial commits look like success (audit A-02).
    """

    def __init__(self, failed_paths: list[Path], message: str | None = None):
        self.failed_paths = list(failed_paths)
        if message is None:
            message = (
                "atomic commit failed for path(s): "
                + ", ".join(str(p) for p in self.failed_paths)
            )
        super().__init__(message)


def _current_bucket() -> dict[Path, str]:
    """Return the pending-writes bucket for the calling thread."""
    tid = threading.get_ident()
    bucket = _pending_writes_by_thread.get(tid)
    if bucket is None:
        bucket = {}
        _pending_writes_by_thread[tid] = bucket
    return bucket


def _atomic_replace(tmp: Path, target: Path) -> None:
    """Replace *target* with *tmp* atomically.

    Prefers ``os.replace`` (atomic on POSIX + Windows when possible).
    Falls back to ``unlink + rename`` when Windows denies ``os.replace``
    (e.g. target file has a security descriptor that blocks
    ``MoveFileExW`` with ``MOVEFILE_REPLACE_EXISTING``).
    """
    for attempt in range(5):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt < 4:
                time.sleep(0.05 * (attempt + 1))
                continue
        break
    # os.replace failed 5 times — fall back to unlink + rename
    try:
        os.unlink(target)
    except FileNotFoundError:
        pass
    os.rename(tmp, target)


def safe_write(path: Union[str, Path], content: str) -> None:
    """Write file, respecting AtomicContext; sentinel content queues deletion.

    Non-suspended path: atomic write via *.tmp + os.replace (no torn writes).
    Suspended path: buffer the (path, content) into the current thread's
    bucket in _pending_writes_by_thread for the AtomicContext commit point.
    DELETE_SENTINEL is always buffered while suspended; while not suspended
    it triggers an immediate os.unlink.
    """
    path = Path(path)
    if is_suspended():
        _current_bucket()[path] = content
        return
    if content == DELETE_SENTINEL:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    _atomic_replace(tmp, path)


def flush_pending_writes() -> int:
    """Flush the current thread's queued writes and deletions at the atomic
    commit point.

    Each flushed write uses the same tmp+replace atomic pattern; each
    queued DELETE_SENTINEL triggers an os.unlink (tolerating missing files).
    Only the current thread's bucket is flushed — other threads'
    pending work remains in their buckets and will be committed by their
    own AtomicContext exit.

    R3 (audit A-02): every path is attempted even if some fail; when any
    path fails, ``AtomicCommitError`` is raised with the aggregated
    ``failed_paths`` list. The old behaviour (log-and-continue) let a
    partial commit look like success — callers must now observe the error
    and mark the task FAILED.
    """
    bucket = _pending_writes_by_thread.pop(threading.get_ident(), {})
    if not bucket:
        return 0
    count = len(bucket)
    failed: list[Path] = []
    for path, content in list(bucket.items()):
        try:
            if content == DELETE_SENTINEL:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(content, encoding="utf-8")
                _atomic_replace(tmp, path)
        except Exception:
            failed.append(path)
            _logger.exception("atomic flush write failed for %s", path)
    if failed:
        raise AtomicCommitError(failed)
    return count


def get_pending_count() -> int:
    """Return the number of pending writes for the current thread."""
    return len(_pending_writes_by_thread.get(threading.get_ident(), {}))


def _reset_for_testing() -> None:
    """Test-only: drop every thread's pending-writes bucket."""
    _pending_writes_by_thread.clear()
