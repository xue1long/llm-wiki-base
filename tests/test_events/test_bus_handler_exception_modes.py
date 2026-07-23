"""Tests for EventBus.fail_fast mode + default exception handling.

Before T8, EventBus caught all handler exceptions and only logged them. T8
adds a `fail_fast: bool = False` attribute; when True, the first handler
exception aborts emit and re-raises. In the default mode, exceptions are
still swallowed (backwards compatible) but the log record now carries the
event name and handler qualname under `extra`.
"""
import logging

import pytest

from src.events.event_bus import EventBus


def test_fail_fast_default_false():
    bus = EventBus()
    assert bus.fail_fast is False


def test_fail_fast_true_aborts_and_reraises():
    bus = EventBus()
    bus.fail_fast = True
    state = {"after_called": False, "bad_called": False}

    def bad_handler(payload):
        state["bad_called"] = True
        raise ValueError("boom")

    def after(payload):
        state["after_called"] = True

    bus.on("x", bad_handler)
    bus.on("x", after)
    with pytest.raises(ValueError, match="boom"):
        bus.emit("x", {})
    # bad_handler always ran (it raised); the ValueError was caught above.
    assert state["bad_called"] is True
    # If `after` happened to run first (set order), bad_handler then raised
    # and aborted — that path is valid. If bad_handler ran first, after
    # was skipped. Both pass fail_fast's contract.


def test_default_mode_swallows_exceptions_continues_iteration():
    """fail_fast=False (default) keeps the legacy behaviour: log and continue."""
    bus = EventBus()
    seen = set()

    def bad_handler(payload):
        seen.add("bad")
        raise ValueError("boom")

    def after(payload):
        seen.add("after")

    bus.on("x", bad_handler)
    bus.on("x", after)
    bus.emit("x", {})  # must not raise
    # Both handlers were called despite the exception in bad_handler.
    assert seen == {"bad", "after"}


def test_handler_exception_logged_with_extra(caplog):
    """Default mode logs handler exceptions with event + qualname in extra."""
    bus = EventBus()

    def bad_handler(payload):
        raise RuntimeError("kaboom")

    bus.on("y", bad_handler)
    with caplog.at_level(logging.ERROR, logger="src.events.event_bus"):
        bus.emit("y", {})
    rec = next(r for r in caplog.records if "kaboom" in r.getMessage())
    assert getattr(rec, "event", None) == "y"
    # __qualname__ includes the enclosing scope (test function + locals);
    # we only assert that the function name appears in it.
    assert "bad_handler" in getattr(rec, "handler", "")


def test_fail_fast_propagates_first_exception_only():
    """In fail_fast mode, the second handler is not invoked once the first
    one raises. Set iteration order is not guaranteed, so we check that
    exactly one of (first, second) ran before the exception aborted emit."""
    bus = EventBus()
    bus.fail_fast = True

    state = {"first_called": False, "second_called": False}

    def first(payload):
        state["first_called"] = True
        raise KeyError("first")

    def second(payload):
        state["second_called"] = True
        raise IndexError("second")

    bus.on("z", first)
    bus.on("z", second)
    with pytest.raises((KeyError, IndexError)):
        bus.emit("z", {})
    # Exactly one of the two raised; the other was never reached because
    # emit aborted on the first exception.
    called = {state["first_called"], state["second_called"]}
    assert called == {True, False}, (
        f"Expected exactly one handler to run before abort; got {state}"
    )