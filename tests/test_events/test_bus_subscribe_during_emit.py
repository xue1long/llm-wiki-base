"""Regression test for I-events-1: EventBus must not crash when a handler
subscribes a new handler to the same event while emit() is iterating.

Before T8, EventBus.emit iterated `self._handlers[event]` directly. When a
handler called bus.on(...) during iteration, the underlying set grew, raising
RuntimeError("Set changed size during iteration"). T8 changes emit() to
iterate a `list(...)` snapshot so subscribing during emit is safe.
"""
from src.events.event_bus import EventBus


def test_subscribe_during_emit_does_not_crash():
    bus = EventBus()

    def handler_c(payload):
        handler_c.called = True
    handler_c.called = False

    def handler_a(payload):
        # Subscribe a brand-new handler while emit() is iterating.
        bus.on("x", handler_c)

    bus.on("x", handler_a)
    # Must NOT raise RuntimeError("Set changed size during iteration")
    bus.emit("x", {})
    # handler_c was added during emit but is NOT called for the current emit
    # (snapshot is taken at start of emit).
    assert handler_c.called is False


def test_subscribe_during_emit_visible_on_next_emit():
    """Handlers added during emit are visible on the NEXT emit."""
    bus = EventBus()
    seen = []

    def handler_a(payload):
        seen.append("a")
        def late(payload):
            seen.append("late")
        bus.on("x", late)

    bus.on("x", handler_a)
    bus.emit("x", {})
    assert sorted(seen) == ["a"]
    bus.emit("x", {})
    # Second emit: both a and late run (order is non-deterministic across sets).
    assert sorted(seen) == ["a", "a", "late"]


def test_unsubscribe_during_emit_does_not_crash():
    """Removing a handler during emit is also safe with the snapshot."""
    bus = EventBus()

    def handler_a(payload):
        bus.off("x", handler_b)  # try to remove handler_b during emit

    def handler_b(payload):
        pass

    bus.on("x", handler_a)
    bus.on("x", handler_b)
    # Must not raise.
    bus.emit("x", {})