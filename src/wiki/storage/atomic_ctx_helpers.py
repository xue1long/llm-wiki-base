"""Convenience wrapper combining AtomicContext + flush_pending_writes."""
from contextlib import contextmanager

from ...lib.atomic_ctx import AtomicContext
from ...lib.write_hooks import flush_pending_writes
from ..core.paths import WikiPaths


@contextmanager
def atomic_pipeline_op(paths: WikiPaths):
    """Context manager that batches all safe_write() calls until exit.

    On outer exit, flush_pending_writes() runs and commits every accumulated
    file in one batch. Use for multi-step operations like cascade_delete
    where partial failure should leave the wiki unchanged.
    """
    with AtomicContext(flush_callback=flush_pending_writes):
        yield