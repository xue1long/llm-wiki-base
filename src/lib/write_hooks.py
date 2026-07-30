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
import os
import threading
import time
from pathlib import Path
from typing import Union

from .atomic_ctx import is_suspended


DELETE_SENTINEL = "__WIKI_DELETE__"
# Per-thread buckets of pending writes. Each thread owns its bucket; only
# that thread reads/writes to it during normal flow. AtomicContext.__exit__
# flushes and clears only the exiting thread's bucket.
_pending_writes_by_thread: dict[int, dict[Path, str]] = {}


def _current_bucket() -> dict[Path, str]:
    """Return the pending-writes bucket for the calling thread."""
    tid = threading.get_ident()
    bucket = _pending_writes_by_thread.get(tid)
    if bucket is None:
        bucket = {}
        _pending_writes_by_thread[tid] = bucket
    return bucket


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
    # Windows: os.replace may transiently fail with PermissionError under
    # high contention (antivirus, rapid queue saves). Retry a few times.
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def flush_pending_writes() -> int:
    """Flush the current thread's queued writes and deletions at the atomic
    commit point.

    Each flushed write uses the same tmp+replace atomic pattern; each
    queued DELETE_SENTINEL triggers an os.unlink (tolerating missing files).
    Only the current thread's bucket is flushed — other threads'
    pending work remains in their buckets and will be committed by their
    own AtomicContext exit.
    """
    bucket = _pending_writes_by_thread.pop(threading.get_ident(), {})
    if not bucket:
        return 0
    count = len(bucket)
    for path, content in list(bucket.items()):
        if content == DELETE_SENTINEL:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
    return count


def get_pending_count() -> int:
    """Return the number of pending writes for the current thread."""
    return len(_pending_writes_by_thread.get(threading.get_ident(), {}))


def _reset_for_testing() -> None:
    """Test-only: drop every thread's pending-writes bucket."""
    _pending_writes_by_thread.clear()