# ruflo-kb/tests/test_events.py
import pytest
from src.events.event_bus import EventBus

def test_event_bus_register_and_call():
    bus = EventBus()
    result = {}

    def handler(payload):
        result["data"] = payload["data"]

    unsub = bus.on("test", handler)
    bus.emit("test", {"data": 42})

    assert result["data"] == 42
    unsub()

def test_event_bus_unsubscribe():
    bus = EventBus()
    called = False

    def handler(_):
        nonlocal called
        called = True

    unsub = bus.on("test", handler)
    unsub()
    bus.emit("test", {})

    assert not called

def test_event_bus_multiple_handlers():
    bus = EventBus()
    results = []

    bus.on("test", lambda _: results.append(1))
    bus.on("test", lambda _: results.append(2))
    bus.emit("test", {})

    assert 1 in results
    assert 2 in results
