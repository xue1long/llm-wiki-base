import threading

from src.lib.atomic_ctx import AtomicContext, is_suspended, __reset_for_testing


def setup_function(_):
    __reset_for_testing()


def test_is_suspended_false_initially():
    assert is_suspended() is False


def test_enter_sets_suspended():
    with AtomicContext():
        assert is_suspended() is True
    assert is_suspended() is False


def test_nested_outer_keeps_suspended():
    with AtomicContext():
        assert is_suspended() is True
        with AtomicContext():
            assert is_suspended() is True
        # Inner exit doesn't reset
        assert is_suspended() is True
    assert is_suspended() is False


def test_flush_callback_runs_on_exit():
    calls = []
    with AtomicContext(flush_callback=lambda: calls.append("flushed")):
        pass
    assert calls == ["flushed"]


def test_flush_callback_not_called_on_inner_exit():
    calls = []
    with AtomicContext(flush_callback=lambda: calls.append("flushed")):
        with AtomicContext():
            pass
        # Inner exit doesn't trigger flush
        assert calls == []
    # Outer exit triggers flush
    assert calls == ["flushed"]


def test_exception_propagates_and_still_flushes():
    calls = []
    try:
        with AtomicContext(flush_callback=lambda: calls.append("flushed")):
            raise ValueError("oops")
    except ValueError:
        pass
    # Flush still runs (finally-like behavior)
    assert calls == ["flushed"]


def test_thread_isolation():
    """AtomicContext in thread A doesn't affect thread B."""
    a_state = []
    b_state = []
    barrier = threading.Barrier(2)

    def in_thread_a():
        with AtomicContext():
            a_state.append(("inside", is_suspended()))
            barrier.wait()  # sync with B
            a_state.append(("after_b", is_suspended()))

    def in_thread_b():
        barrier.wait()  # sync with A
        b_state.append(("after_a", is_suspended()))

    ta = threading.Thread(target=in_thread_a)
    tb = threading.Thread(target=in_thread_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    assert a_state == [("inside", True), ("after_b", True)]
    assert b_state == [("after_a", False)]  # B never entered AtomicContext