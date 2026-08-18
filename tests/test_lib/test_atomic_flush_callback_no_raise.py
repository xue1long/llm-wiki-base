"""R3: AtomicContext.__exit__ must propagate commit failures.

Old contract (pre-R3): flush_callback failures were logged and never
raised. R3 (audit A-02) reverses this: a callback failure is a commit
failure and must surface to the caller so the task can be marked FAILED.
The body-exception rule is unchanged — a body exception still wins and
the callback is not invoked (audit C1).
"""
import pytest

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_flush_callback_failure_propagates():
    """A failing flush_callback raises out of __exit__ (R3)."""
    def failing_callback():
        raise RuntimeError("callback exploded")

    with pytest.raises(RuntimeError, match="callback exploded"):
        with AtomicContext(flush_callback=failing_callback):
            pass


def test_flush_callback_failure_does_not_suppress_body_exception():
    """Body exceptions still propagate; callback is not invoked when body raises."""
    def failing_callback():
        raise RuntimeError("callback exploded")

    raised = None
    try:
        with AtomicContext(flush_callback=failing_callback):
            raise ValueError("body exploded")
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert str(raised) == "body exploded"
