"""Verify per-thread isolation of pending writes.

Concurrent AtomicContext instances in different threads must not share
or overwrite each other's pending writes. Each thread's bucket is
flushed only by that thread's AtomicContext exit.
"""
import threading
from pathlib import Path

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_threads_have_independent_pending_buckets():
    """Two threads in AtomicContext get distinct buckets, not one shared dict."""
    barrier = threading.Barrier(2)
    snapshots = {}

    def worker(name: str, path, content):
        barrier.wait()
        with AtomicContext():
            write_hooks.safe_write(path, content)
            # While inside the context, dump the bucket the helper sees.
            snapshots[name] = dict(write_hooks._current_bucket())

    a = Path("alpha.txt")
    b = Path("beta.txt")
    ta = threading.Thread(target=worker, args=("a", a, "alpha-content"))
    tb = threading.Thread(target=worker, args=("b", b, "beta-content"))
    ta.start(); tb.start()
    ta.join(); tb.join()

    # Each thread observed only its own buffered write.
    assert snapshots["a"] == {a: "alpha-content"}
    assert snapshots["b"] == {b: "beta-content"}


def test_thread_a_exit_does_not_flush_thread_b_bucket():
    """A thread exiting its context must not touch other threads' buckets."""
    start_b = threading.Event()
    b_done = threading.Event()
    b_snapshot = {}
    observed = {}

    def thread_b():
        with AtomicContext():
            write_hooks.safe_write(Path("shared.txt"), "from-B")
            b_snapshot["bucket_during"] = dict(write_hooks._current_bucket())
            start_b.set()
            # Hold the context open until A has exited.
            b_done.wait(timeout=5.0)
            b_snapshot["bucket_after_wait"] = dict(write_hooks._current_bucket())

    def thread_a():
        with AtomicContext():
            write_hooks.safe_write(Path("a.txt"), "from-A")
        # A exited first; thread B's bucket should still hold its write.

    tb = threading.Thread(target=thread_b)
    tb.start()
    start_b.wait(timeout=2.0)
    ta = threading.Thread(target=thread_a)
    ta.start()
    ta.join()
    # Snapshot mid-test, while B is still in its context.
    observed["b_bucket_via_dict"] = dict(
        write_hooks._pending_writes_by_thread.get(tb.ident, {})
    )
    observed["all_keys"] = list(write_hooks._pending_writes_by_thread.keys())
    observed["thread_b_ident"] = tb.ident
    b_done.set()
    tb.join()
    observed["bucket_during"] = b_snapshot.get("bucket_during")
    observed["bucket_after_wait"] = b_snapshot.get("bucket_after_wait")

    # Thread B's bucket is preserved while its context is open.
    assert observed["bucket_during"] == {Path("shared.txt"): "from-B"}, observed
    # After thread A exited, B's bucket is still untouched.
    assert observed["b_bucket_via_dict"] == {Path("shared.txt"): "from-B"}, observed