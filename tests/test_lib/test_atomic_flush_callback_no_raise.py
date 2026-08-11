"""Verify that AtomicContext.__exit__ NEVER raises from flush_callback.

The contract from `src/lib/atomic_ctx.py`'s docstring is:
"All safe_write() calls ... flush_callback runs once on outer exit, providing
a single batched commit point." — and the implementation comment says flush
failures are logged but never raised. If the body had no exception, a
flush_callback exception must not propagate.
"""
import logging

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_flush_callback_failure_does_not_raise_with_no_body_exception(caplog):
    def failing_callback():
        raise RuntimeError("callback exploded")

    with caplog.at_level(logging.ERROR, logger="src.lib.atomic_ctx"):
        with AtomicContext(flush_callback=failing_callback):
            pass

    assert any("flush_callback failed" in rec.message for rec in caplog.records)


def test_flush_callback_failure_does_not_suppress_body_exception(caplog):
    """Body exceptions still propagate; callback is not invoked when body raises.

    With the audit C1 fix the flush_callback is no longer invoked when the
    body raised. The body's exception still propagates and is the only thing
    the caller observes — partial state is discarded so a callback failure
    cannot mask the original error.
    """
    def failing_callback():
        raise RuntimeError("callback exploded")

    raised = None
    with caplog.at_level(logging.ERROR, logger="src.lib.atomic_ctx"):
        try:
            with AtomicContext(flush_callback=failing_callback):
                raise ValueError("body exploded")
        except ValueError as exc:
            raised = exc

    assert raised is not None
    assert str(raised) == "body exploded"
    # Callback is not invoked when the body raised.
    assert not any("flush_callback failed" in rec.message for rec in caplog.records)
