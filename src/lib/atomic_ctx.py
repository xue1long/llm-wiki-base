"""AtomicContext — thread-local suspend flag + context manager.

Multi-step operations (cascade_delete / lint --fix / dedup auto) wrap
their writes in AtomicContext. All safe_write() calls check the flag
and skip disk I/O while suspended. The flush_callback runs once on
outer exit, providing a single batched commit point.
"""
import logging
import threading
from typing import Callable, Optional


_logger = logging.getLogger(__name__)

# Thread-local state: each thread has its own suspend flag and stack depth.
# This ensures AtomicContext in one thread does not affect another thread.
_thread_state = threading.local()


def _get_local() -> dict:
    """Get or initialize thread-local state."""
    if not hasattr(_thread_state, "suspended"):
        _thread_state.suspended = False
        _thread_state.stack_depth = 0
    return _thread_state


def is_suspended() -> bool:
    """Returns True if any AtomicContext is active in the current thread."""
    return _get_local().suspended


class AtomicContext:
    """Suspends all disk-write hooks until exit.

    Usage:
        with AtomicContext(flush_callback=merge_pending_writes):
            page_writer.write(page_a)   # skipped (writes go to pending)
            page_writer.write(page_b)   # skipped
        # exit: flush_callback() merges page_a + page_b writes + flushes

    Nested:
        with AtomicContext():
            with AtomicContext():  # inner is no-op
                ...

    Thread safety: per-thread counter and flag. Each thread has its own
    AtomicContext stack, so threads do not interfere with each other.
    """

    def __init__(self, flush_callback: Optional[Callable[[], None]] = None):
        self._flush_callback = flush_callback
        self._is_outer = False

    def __enter__(self) -> "AtomicContext":
        local = _get_local()
        if local.stack_depth == 0:
            self._is_outer = True
            local.suspended = True
        local.stack_depth += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        local = _get_local()
        local.stack_depth -= 1
        if local.stack_depth > 0:
            return False

        from . import write_hooks

        bucket = write_hooks._current_bucket()

        # Audit fix (C1): an exception raised in the body MUST NOT commit
        # buffered writes. Discard the pending bucket so partial state is
        # not flushed. The body's exception continues to propagate.
        if exc_type is not None:
            bucket.clear()
            local.suspended = False
            return False

        local.suspended = False
        if not (self._is_outer and self._flush_callback):
            return False

        # Snapshot and clear only THIS thread's pending-writes bucket. Other
        # threads' buckets are untouched; their AtomicContext exit will flush
        # them. See src/lib/write_hooks.py for the per-thread design.
        pending = list(bucket.items())
        bucket.clear()

        # Flush the captured batch one path at a time so a failed write does
        # not prevent the remaining paths from reaching disk. The bucket is
        # already clear, so callback failures cannot leak writes.
        for path, content in pending:
            try:
                write_hooks.safe_write(path, content)
            except Exception:
                _logger.exception("atomic flush write failed for %s", path)
        try:
            self._flush_callback()
        except Exception as e:
            _logger.error(f"[AtomicContext] flush_callback failed: {e}")
            # Docstring contract: "flush failures logged but never raised from
            # __exit__". A body exception already wins the propagation slot, so
            # we must swallow callback failures unconditionally to honour it.
        return False


def __reset_for_testing() -> None:
    """Drop state. Test-only. Resets thread-local state for the current thread."""
    if hasattr(_thread_state, "suspended"):
        _thread_state.suspended = False
        _thread_state.stack_depth = 0
