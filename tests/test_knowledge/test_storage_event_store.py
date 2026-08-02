"""Test EventStore — JSONL + Postgres backends (Task 5.3)."""
import json
import time
from pathlib import Path

import pytest

from src.knowledge.storage.event_store import (
    EventStore,
    JSONLEventStore,
    PostgresEventStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """Return a fresh JSONLEventStore backed by a temporary directory."""
    return JSONLEventStore(index_path=tmp_path)


# ---------------------------------------------------------------------------
# Test JSONLEventStore: append
# ---------------------------------------------------------------------------


def test_jsonl_append_returns_version_1(store):
    """Append event -> returns version 1."""
    version = store.append("stream_a", "node_created", {"node_id": "n1"})
    assert version == 1


def test_jsonl_version_increments(store):
    """Two appends -> versions 1, 2."""
    v1 = store.append("stream_a", "node_created", {"node_id": "n1"})
    v2 = store.append("stream_a", "node_updated", {"node_id": "n1", "label": "X"})
    assert v1 == 1
    assert v2 == 2


# ---------------------------------------------------------------------------
# Test JSONLEventStore: read_all
# ---------------------------------------------------------------------------


def test_jsonl_read_all_returns_all_events(store):
    """Append 3 events -> read_all returns 3."""
    store.append("s1", "t1", {"k": "v1"})
    store.append("s1", "t2", {"k": "v2"})
    store.append("s2", "t3", {"k": "v3"})
    events = store.read_all()
    assert len(events) == 3


def test_jsonl_read_all_since_timestamp(store):
    """Append events at different times -> filter by timestamp."""
    t1 = int(time.time() * 1000)
    store.append("s1", "e1", {"n": 1})
    time.sleep(0.01)  # ensure timestamp gap
    t2 = int(time.time() * 1000)
    store.append("s1", "e2", {"n": 2})
    store.append("s1", "e3", {"n": 3})

    # since_timestamp=t2 excludes the first event
    events = store.read_all(since_timestamp=t2)
    assert len(events) == 2
    event_types = [e["action"] for e in events]
    assert "e2" in event_types
    assert "e3" in event_types


# ---------------------------------------------------------------------------
# Test JSONLEventStore: read_stream
# ---------------------------------------------------------------------------


def test_jsonl_read_stream_filters_by_stream(store):
    """Append events to two streams -> read_stream filters correctly."""
    store.append("stream_a", "e1", {"v": 1})
    store.append("stream_a", "e2", {"v": 2})
    store.append("stream_b", "e3", {"v": 3})
    store.append("stream_b", "e4", {"v": 4})

    events_a = store.read_stream("stream_a")
    assert len(events_a) == 2
    assert all(e["stream_id"] == "stream_a" for e in events_a)

    events_b = store.read_stream("stream_b")
    assert len(events_b) == 2
    assert all(e["stream_id"] == "stream_b" for e in events_b)


def test_jsonl_read_stream_since_version(store):
    """Append 5 events, read since_version=3 -> returns 2 events."""
    for i in range(5):
        store.append("stream_a", f"e{i + 1}", {"n": i + 1})

    events = store.read_stream("stream_a", since_version=3)
    assert len(events) == 2
    versions = [e["event_version"] for e in events]
    assert versions == [4, 5]


def test_jsonl_read_stream_nonexistent_stream(store):
    """Read from a stream with no events -> returns empty list."""
    events = store.read_stream("nonexistent")
    assert events == []


# ---------------------------------------------------------------------------
# Test JSONLEventStore: count
# ---------------------------------------------------------------------------


def test_jsonl_count_total(store):
    """5 events -> count() = 5."""
    for i in range(5):
        store.append(f"s{i % 2}", f"e{i}", {"n": i})
    assert store.count() == 5


def test_jsonl_count_stream(store):
    """3 in stream_a, 2 in stream_b -> count('stream_a') = 3."""
    store.append("stream_a", "e1", {})
    store.append("stream_a", "e2", {})
    store.append("stream_b", "e3", {})
    store.append("stream_a", "e4", {})
    store.append("stream_b", "e5", {})
    assert store.count("stream_a") == 3
    assert store.count("stream_b") == 2


def test_jsonl_empty_store(store):
    """New store -> read_all returns [], count = 0, read_stream returns []."""
    assert store.read_all() == []
    assert store.count() == 0
    assert store.read_stream("any") == []


# ---------------------------------------------------------------------------
# Test JSONLEventStore: event format
# ---------------------------------------------------------------------------


def test_jsonl_event_format(store):
    """Each event has stream_id, action, event_version, timestamp + payload spread."""
    store.append("my_stream", "my_event", {"key": "value"})
    events = store.read_all()
    assert len(events) == 1
    event = events[0]
    assert event["stream_id"] == "my_stream"
    assert event["action"] == "my_event"
    assert event["event_version"] == 1
    assert event["key"] == "value"  # payload spread at top level
    assert isinstance(event["timestamp"], int)
    assert event["timestamp"] > 0


def test_jsonl_event_format_raw_file(store):
    """Raw JSONL line contains all expected fields."""
    store.append("s", "t", {"p": 1})
    raw = store.get_events_path().read_text(encoding="utf-8")
    lines = [l for l in raw.strip().split("\n") if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["action"] == "t"
    assert parsed["stream_id"] == "s"
    assert parsed["event_version"] == 1
    assert parsed["p"] == 1
    assert "timestamp" in parsed


# ---------------------------------------------------------------------------
# Test JSONLEventStore: directory creation
# ---------------------------------------------------------------------------


def test_jsonl_creates_directory(tmp_path):
    """Init with non-existent path -> directory created."""
    index_path = tmp_path / "sub" / "nested"
    assert not index_path.exists()
    store = JSONLEventStore(index_path=index_path)
    assert store.get_events_path().parent.exists()


# ---------------------------------------------------------------------------
# Test JSONLEventStore: persistence across instances
# ---------------------------------------------------------------------------


def test_jsonl_loads_existing_events(tmp_path):
    """Create store, append, create new store on same path -> read_all returns existing events."""
    store1 = JSONLEventStore(index_path=tmp_path)
    store1.append("s1", "e1", {"n": 1})
    store1.append("s1", "e2", {"n": 2})

    # New instance on same path
    store2 = JSONLEventStore(index_path=tmp_path)
    events = store2.read_all()
    assert len(events) == 2
    versions = [e["event_version"] for e in events]
    assert versions == [1, 2]


# ---------------------------------------------------------------------------
# Test JSONLEventStore: get_events_path
# ---------------------------------------------------------------------------


def test_jsonl_get_events_path(store):
    """Returns correct path."""
    expected = store.get_events_path()
    assert expected.name == "events.jsonl"
    assert "knowledge_graph" in str(expected)


# ---------------------------------------------------------------------------
# Test JSONLEventStore: non-store events in file (compatibility)
# ---------------------------------------------------------------------------


def test_jsonl_skips_non_store_events(store):
    """Events without stream_id are skipped by count and read operations."""
    events_path = store.get_events_path()
    # Write a GraphBuilder-style event directly to the file
    legacy_event = json.dumps({
        "action": "upsert_node",
        "node": {"id": "n1", "type": "entity", "label": "X", "properties": {}},
        "timestamp": int(time.time() * 1000),
        "event_index": 1,
    }, ensure_ascii=False) + "\n"
    with open(events_path, "a", encoding="utf-8") as fh:
        fh.write(legacy_event)
        fh.flush()

    # Append a proper store event
    store.append("s1", "e1", {"k": "v"})

    # read_all only returns events with occurred_at
    all_events = store.read_all()
    # The legacy event has no occurred_at -> skipped
    # The store event has occurred_at -> included
    store_events = [e for e in all_events if e.get("stream_id") == "s1"]
    assert len(store_events) == 1

    # count only counts events with stream_id when filtering
    assert store.count() == 2  # both lines are valid JSON
    assert store.count("s1") == 1  # only store event matches stream_id


def test_jsonl_handles_invalid_lines(store):
    """Invalid JSON lines are skipped gracefully."""
    events_path = store.get_events_path()
    with open(events_path, "a", encoding="utf-8") as fh:
        fh.write("this is not valid json\n")
        fh.flush()

    store.append("s1", "e1", {"k": "v"})

    events = store.read_all()
    assert len(events) == 1
    assert events[0]["stream_id"] == "s1"


# ---------------------------------------------------------------------------
# Test EventStore ABC
# ---------------------------------------------------------------------------


def test_event_store_abc_cannot_instantiate():
    """Can't instantiate abstract EventStore."""
    with pytest.raises(TypeError):
        EventStore()  # type: ignore[abstract]


def test_jsonl_is_event_store_subclass():
    """JSONLEventStore is an EventStore subclass."""
    assert issubclass(JSONLEventStore, EventStore)


# ---------------------------------------------------------------------------
# Test PostgresEventStore class structure
# ---------------------------------------------------------------------------


def test_postgres_event_store_class_exists():
    """PostgresEventStore is defined and subclasses EventStore."""
    assert issubclass(PostgresEventStore, EventStore)


def test_postgres_event_store_has_expected_methods():
    """PostgresEventStore exposes the standard EventStore interface."""
    assert hasattr(PostgresEventStore, "append")
    assert hasattr(PostgresEventStore, "read_stream")
    assert hasattr(PostgresEventStore, "read_all")
    assert hasattr(PostgresEventStore, "count")


def test_postgres_event_store_accepts_database_url():
    """PostgresEventStore.__init__ accepts database_url."""
    store = PostgresEventStore(database_url="postgresql://user:pass@localhost/db")
    assert store._database_url == "postgresql://user:pass@localhost/db"
