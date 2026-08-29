"""Test EventStore — JSONL + Postgres backends (Task 5.3)."""
import json
import time

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
# Test JSONLEventStore: append_event (operation_id-keyed idempotency)
# ---------------------------------------------------------------------------


def test_append_event_first_write_returns_ok(store):
    """首次 append_event -> {"status": "ok", "event": {...}}，含 operation_id + payload_hash."""
    result = store.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    assert result["status"] == "ok"
    event = result["event"]
    assert event["operation_id"] == "op-1"
    assert event["payload_hash"]
    assert event["stream_id"] == "s1"
    assert event["action"] == "e1"
    assert event["event_version"] == 1


def test_append_event_idempotent_replay_returns_duplicate(store):
    """相同 operation_id + 相同 payload -> duplicate，返回原事件，不写新事件."""
    r1 = store.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    r2 = store.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    assert r1["status"] == "ok"
    assert r2["status"] == "duplicate"
    assert r2["event"] == r1["event"]
    assert store.count() == 1


def test_append_event_version_conflict_on_different_payload_hash(store):
    """相同 operation_id、不同 payload_hash -> version_conflict，不写任何事件."""
    r1 = store.append_event("s1", "e1", {"k": "v1"}, operation_id="op-1")
    assert r1["status"] == "ok"
    r2 = store.append_event("s1", "e1", {"k": "v2"}, operation_id="op-1")
    assert r2["status"] == "version_conflict"
    assert r2["stored_payload_hash"] == r1["event"]["payload_hash"]
    assert store.count() == 1


def test_append_event_default_payload_hash_is_canonical_sha256(store):
    """payload_hash 默认 = sha256(canonical JSON, sorted keys)."""
    import hashlib

    payload = {"b": 2, "a": 1}
    result = store.append_event("s1", "e1", payload, operation_id="op-1")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert result["event"]["payload_hash"] == expected


def test_append_event_explicit_payload_hash_is_honored(store):
    """显式传入的 payload_hash 被原样记录."""
    result = store.append_event("s1", "e1", {"k": "v"}, operation_id="op-1", payload_hash="hash-abc")
    assert result["event"]["payload_hash"] == "hash-abc"


def test_append_event_cold_start_replay(tmp_path):
    """同一文件上的新 store 实例仍能识别已记录的 operation（冷启动重放）."""
    store1 = JSONLEventStore(index_path=tmp_path)
    r1 = store1.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    assert r1["status"] == "ok"

    store2 = JSONLEventStore(index_path=tmp_path)
    r2 = store2.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    assert r2["status"] == "duplicate"
    assert store2.count() == 1


def test_append_event_coexists_with_append(store):
    """append() 与 append_event() 共用同一事件文件与版本计数器."""
    v1 = store.append("s1", "legacy", {"n": 1})
    r = store.append_event("s1", "idem", {"n": 2}, operation_id="op-1")
    assert v1 == 1
    assert r["event"]["event_version"] == 2
    assert store.count() == 2


def test_append_event_concurrent_same_instance_exactly_one_ok(tmp_path):
    """两线程（同一 store 实例）并发 append_event 同一 operation_id →
    恰好一个 ok、一个 duplicate（非 version_conflict），且只写一条事件."""
    import threading

    store = JSONLEventStore(index_path=tmp_path)
    results: list[dict] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=10)
        except BaseException as exc:  # pragma: no cover - barrier should not fail
            errors.append(exc)
            return
        try:
            results.append(
                store.append_event("s1", "e1", {"k": "v"}, operation_id="op-race")
            )
        except BaseException as exc:  # pragma: no cover - assertion helper
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(r["status"] for r in results) == ["duplicate", "ok"]
    assert all(r["event"]["operation_id"] == "op-race" for r in results)
    assert store.count() == 1


def test_append_event_concurrent_two_instances_same_file_exactly_one_ok(tmp_path):
    """两个 store 实例（各自冷启动索引，模拟并发进程）指向同一文件并发
    append_event 同一 operation_id → 恰好一个 ok、一个 duplicate."""
    import threading

    store_a = JSONLEventStore(index_path=tmp_path)
    store_b = JSONLEventStore(index_path=tmp_path)
    results: list[dict] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(store):
        try:
            barrier.wait(timeout=10)
        except BaseException as exc:  # pragma: no cover - barrier should not fail
            errors.append(exc)
            return
        try:
            results.append(
                store.append_event("s1", "e1", {"k": "v"}, operation_id="op-race-2")
            )
        except BaseException as exc:  # pragma: no cover - assertion helper
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(store_a,)),
        threading.Thread(target=worker, args=(store_b,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(r["status"] for r in results) == ["duplicate", "ok"]
    assert store_a.count() == 1
    assert store_b.count() == 1


def test_facade_append_event_pass_through(tmp_path):
    """StorageFacade 暴露 append_event 作为到活动 event store 的透传."""
    from src.knowledge.storage.facade import StorageConfig, StorageFacade

    facade = StorageFacade(StorageConfig(wiki_path=tmp_path, index_path=tmp_path))
    r1 = facade.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    r2 = facade.append_event("s1", "e1", {"k": "v"}, operation_id="op-1")
    assert r1["status"] == "ok"
    assert r2["status"] == "duplicate"
    assert facade.events.count() == 1


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
