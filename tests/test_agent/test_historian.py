"""Tests for HistorianAgent — structured change history via EventBus subscription."""

import json
import time
from pathlib import Path

import pytest

from src.agent.historian import (
    ChangeRecord,
    HistorianAgent,
    _change_record_to_dict,
    _dict_to_change_record,
)
from src.events.event_bus import EventBus
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wiki_paths(tmp_path):
    """Create a WikiPaths pointing at a temp project root."""
    return WikiPaths(root=tmp_path)


@pytest.fixture
def event_bus():
    """Create a fresh EventBus instance for each test."""
    return EventBus()


@pytest.fixture
def historian(wiki_paths, event_bus):
    """Create a HistorianAgent with a fresh EventBus."""
    return HistorianAgent(wiki_paths=wiki_paths, event_bus=event_bus)


# ---------------------------------------------------------------------------
# ChangeRecord dataclass tests
# ---------------------------------------------------------------------------


class TestChangeRecord:
    """ChangeRecord dataclass field validation."""

    def test_all_fields_present_and_correct(self):
        """All fields are stored correctly in the dataclass."""
        record = ChangeRecord(
            timestamp=1000,
            agent="curator",
            agent_id="curator-001",
            object_id="obj-123",
            change_type="content_update",
            before_snapshot_id="v1",
            after_snapshot_id="v2",
            reason="Fixed typo",
            details={"field": "title", "old_value": "Hello", "new_value": "Hi"},
        )
        assert record.timestamp == 1000
        assert record.agent == "curator"
        assert record.agent_id == "curator-001"
        assert record.object_id == "obj-123"
        assert record.change_type == "content_update"
        assert record.before_snapshot_id == "v1"
        assert record.after_snapshot_id == "v2"
        assert record.reason == "Fixed typo"
        assert record.details == {"field": "title", "old_value": "Hello", "new_value": "Hi"}

    def test_details_defaults_to_empty_dict(self):
        """details field defaults to empty dict when not provided."""
        record = ChangeRecord(
            timestamp=1000,
            agent="system",
            agent_id="",
            object_id="obj-1",
            change_type="content_update",
            before_snapshot_id="",
            after_snapshot_id="",
            reason="test",
        )
        assert record.details == {}

    def test_serialize_roundtrip(self):
        """ChangeRecord serializes to dict and back without data loss."""
        original = ChangeRecord(
            timestamp=1000,
            agent="curator",
            agent_id="curator-001",
            object_id="obj-123",
            change_type="content_update",
            before_snapshot_id="v1",
            after_snapshot_id="v2",
            reason="Fixed typo",
            details={"field": "title", "old_value": "Hello"},
        )
        as_dict = _change_record_to_dict(original)
        restored = _dict_to_change_record(as_dict)
        assert restored.timestamp == original.timestamp
        assert restored.agent == original.agent
        assert restored.agent_id == original.agent_id
        assert restored.object_id == original.object_id
        assert restored.change_type == original.change_type
        assert restored.before_snapshot_id == original.before_snapshot_id
        assert restored.after_snapshot_id == original.after_snapshot_id
        assert restored.reason == original.reason
        assert restored.details == original.details


# ---------------------------------------------------------------------------
# HistorianAgent tests
# ---------------------------------------------------------------------------


class TestHistorianRecordChange:
    """Tests for record_change() — direct change recording."""

    def test_record_change_writes_to_jsonl(self, historian: HistorianAgent):
        """record_change() creates a JSONL file with the correct JSON line."""
        record = historian.record_change(
            object_id="obj-1",
            change_type="content_update",
            reason="Initial creation",
        )

        filepath = historian._history_dir / "obj-1.jsonl"
        assert filepath.exists()

        lines = filepath.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["object_id"] == "obj-1"
        assert data["change_type"] == "content_update"
        assert data["agent"] == "system"
        assert data["reason"] == "Initial creation"

    def test_record_change_returns_change_record(self, historian: HistorianAgent):
        """record_change() returns the created ChangeRecord."""
        record = historian.record_change(
            object_id="obj-1",
            change_type="content_update",
            reason="Test",
            agent="curator",
        )
        assert isinstance(record, ChangeRecord)
        assert record.object_id == "obj-1"
        assert record.agent == "curator"
        assert record.change_type == "content_update"

    def test_record_change_includes_timestamp(self, historian: HistorianAgent):
        """record_change() sets timestamp to current time."""
        before = int(time.time() * 1000)
        record = historian.record_change(
            object_id="obj-1",
            change_type="content_update",
            reason="Test",
        )
        after = int(time.time() * 1000)
        assert before <= record.timestamp <= after + 1

    def test_record_change_custom_fields(self, historian: HistorianAgent):
        """record_change() stores all custom fields correctly."""
        record = historian.record_change(
            object_id="obj-1",
            change_type="relation_change",
            reason="Added relation",
            agent="curator",
            agent_id="curator-007",
            before_snapshot_id="snap-before",
            after_snapshot_id="snap-after",
            details={"relation_type": "references", "target": "obj-2"},
        )
        assert record.agent == "curator"
        assert record.agent_id == "curator-007"
        assert record.change_type == "relation_change"
        assert record.before_snapshot_id == "snap-before"
        assert record.after_snapshot_id == "snap-after"
        assert record.details == {"relation_type": "references", "target": "obj-2"}


class TestHistorianGetChangeHistory:
    """Tests for get_change_history()."""

    def test_get_change_history_returns_records_newest_first(
        self, historian: HistorianAgent
    ):
        """get_change_history() returns records sorted by timestamp descending."""
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="First"
        )
        time.sleep(0.01)
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="Second"
        )
        time.sleep(0.01)
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="Third"
        )

        history = historian.get_change_history("obj-1")
        assert len(history) == 3
        # Newest first
        assert history[0].reason == "Third"
        assert history[1].reason == "Second"
        assert history[2].reason == "First"
        for i in range(len(history) - 1):
            assert history[i].timestamp >= history[i + 1].timestamp

    def test_get_change_history_unknown_object_returns_empty(
        self, historian: HistorianAgent
    ):
        """get_change_history() returns empty list for unknown object."""
        history = historian.get_change_history("nonexistent")
        assert history == []

    def test_get_change_history_no_file(self, historian: HistorianAgent):
        """get_change_history() returns empty list when JSONL file does not exist."""
        history = historian.get_change_history("never-recorded")
        assert history == []
        assert not (historian._history_dir / "never-recorded.jsonl").exists()


class TestHistorianLifecycleEvent:
    """Tests for EventBus lifecycle event handling."""

    def test_on_lifecycle_changed_creates_record(
        self, wiki_paths: WikiPaths, event_bus: EventBus
    ):
        """Emitting lifecycle.changed creates a ChangeRecord."""
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=event_bus)

        event_bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": "obj-lifecycle-1",
            "from": "created",
            "to": "processing",
            "reason": "Start processing",
            "timestamp": 1000000,
        })

        history = historian.get_change_history("obj-lifecycle-1")
        assert len(history) == 1
        record = history[0]
        assert record.object_id == "obj-lifecycle-1"
        assert record.change_type == "lifecycle_transition"
        assert record.before_snapshot_id == "created"
        assert record.after_snapshot_id == "processing"
        assert record.reason == "Start processing"
        assert record.timestamp == 1000000

    def test_on_lifecycle_changed_defaults_agent(self, historian: HistorianAgent):
        """Lifecycle events without agent field default to 'lifecycle_engine'."""
        historian._event_bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": "obj-no-agent",
            "from": "active",
            "to": "archived",
            "reason": "Archiving",
            "timestamp": 2000000,
        })

        history = historian.get_change_history("obj-no-agent")
        assert len(history) == 1
        assert history[0].agent == "lifecycle_engine"

    def test_on_lifecycle_changed_stores_details(self, historian: HistorianAgent):
        """Lifecycle event stores old_state and new_state in details dict."""
        historian._event_bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": "obj-details",
            "from": "reviewing",
            "to": "active",
            "reason": "Approved",
            "timestamp": 3000000,
        })

        history = historian.get_change_history("obj-details")
        assert len(history) == 1
        assert history[0].details == {"old_state": "reviewing", "new_state": "active"}

    def test_on_lifecycle_changed_does_not_affect_direct_records(
        self, historian: HistorianAgent
    ):
        """Lifecycle events and direct record_change() coexist in same file."""
        # Direct record
        historian.record_change(
            object_id="obj-mixed",
            change_type="content_update",
            reason="Direct change",
        )
        # Lifecycle event
        historian._event_bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": "obj-mixed",
            "from": "active",
            "to": "deprecated",
            "reason": "Deprecating",
            "timestamp": 4000000,
        })

        history = historian.get_change_history("obj-mixed")
        assert len(history) == 2
        change_types = {r.change_type for r in history}
        assert "lifecycle_transition" in change_types
        assert "content_update" in change_types

    def test_multiple_lifecycle_events(self, historian: HistorianAgent):
        """Multiple lifecycle events for the same object are all recorded."""
        for i, (from_state, to_state) in enumerate(
            [("created", "processing"), ("processing", "reviewing"), ("reviewing", "active")]
        ):
            historian._event_bus.emit("lifecycle.changed", {
                "event": "lifecycle.changed",
                "object_id": "obj-multi",
                "from": from_state,
                "to": to_state,
                "reason": f"Transition {i}",
                "timestamp": 1000000 + i * 1000,
            })

        history = historian.get_change_history("obj-multi")
        assert len(history) == 3


class TestHistorianGetChangesByAgent:
    """Tests for get_changes_by_agent()."""

    def test_filters_by_agent_type(self, historian: HistorianAgent):
        """get_changes_by_agent() returns only records matching the agent type."""
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="A", agent="curator"
        )
        historian.record_change(
            object_id="obj-2", change_type="content_update", reason="B", agent="system"
        )
        historian.record_change(
            object_id="obj-3", change_type="content_update", reason="C", agent="curator"
        )

        curator_changes = historian.get_changes_by_agent("curator")
        assert len(curator_changes) == 2
        assert all(r.agent == "curator" for r in curator_changes)

        system_changes = historian.get_changes_by_agent("system")
        assert len(system_changes) == 1
        assert system_changes[0].agent == "system"

    def test_respects_since_timestamp(self, historian: HistorianAgent):
        """get_changes_by_agent() with since filters by timestamp."""
        # Record at t=100 and t=200 (we set exact timestamps for deterministic test)
        # Use record_change but then manually adjust the records via direct file write
        historian.record_change(
            object_id="obj-time-1", change_type="content_update", reason="Early",
            agent="curator",
        )
        historian.record_change(
            object_id="obj-time-2", change_type="content_update", reason="Late",
            agent="curator",
        )

        # Since record_change uses time.time(), we need a different approach:
        # directly write records with known timestamps
        hist_dir = historian._history_dir
        # Write a known-timestamp record
        import json as _json
        from src.agent.historian import _change_record_to_dict

        early = ChangeRecord(
            timestamp=100, agent="processor", agent_id="", object_id="obj-early",
            change_type="content_update", before_snapshot_id="", after_snapshot_id="",
            reason="Early record",
        )
        late = ChangeRecord(
            timestamp=200, agent="processor", agent_id="", object_id="obj-late",
            change_type="content_update", before_snapshot_id="", after_snapshot_id="",
            reason="Late record",
        )
        with open(hist_dir / "obj-early.jsonl", "w", encoding="utf-8") as f:
            f.write(_json.dumps(_change_record_to_dict(early)) + "\n")
        with open(hist_dir / "obj-late.jsonl", "w", encoding="utf-8") as f:
            f.write(_json.dumps(_change_record_to_dict(late)) + "\n")

        # since=150 should return only the late record
        result = historian.get_changes_by_agent("processor", since=150)
        assert len(result) == 1
        assert result[0].reason == "Late record"

        # since=0 should return both
        result_all = historian.get_changes_by_agent("processor", since=0)
        assert len(result_all) == 2

    def test_unknown_agent_returns_empty(self, historian: HistorianAgent):
        """get_changes_by_agent() returns empty list for unknown agent type."""
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="A", agent="curator"
        )
        result = historian.get_changes_by_agent("nonexistent")
        assert result == []


class TestHistorianGetRecentChanges:
    """Tests for get_recent_changes()."""

    def test_returns_limited_count(self, wiki_paths: WikiPaths, event_bus: EventBus):
        """get_recent_changes(limit=N) returns at most N records."""
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=event_bus)
        for i in range(10):
            historian.record_change(
                object_id=f"obj-{i}",
                change_type="content_update",
                reason=f"Change {i}",
            )

        recent = historian.get_recent_changes(limit=5)
        assert len(recent) == 5
        # Sorted newest first
        for j in range(len(recent) - 1):
            assert recent[j].timestamp >= recent[j + 1].timestamp

    def test_limit_exceeds_total_returns_all(
        self, wiki_paths: WikiPaths, event_bus: EventBus
    ):
        """get_recent_changes() returns all records when limit > total."""
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=event_bus)
        for i in range(3):
            historian.record_change(
                object_id=f"obj-{i}",
                change_type="content_update",
                reason=f"Change {i}",
            )

        recent = historian.get_recent_changes(limit=100)
        assert len(recent) == 3

    def test_no_records_returns_empty(self, historian: HistorianAgent):
        """get_recent_changes() returns empty list when no records exist."""
        recent = historian.get_recent_changes()
        assert recent == []

    def test_aggregates_across_objects(
        self, wiki_paths: WikiPaths, event_bus: EventBus
    ):
        """get_recent_changes() aggregates records across all objects."""
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=event_bus)

        # Write records with known timestamps for deterministic ordering
        import json as _json
        from src.agent.historian import _change_record_to_dict

        rec_a = ChangeRecord(
            timestamp=500, agent="system", agent_id="", object_id="obj-a",
            change_type="content_update", before_snapshot_id="", after_snapshot_id="",
            reason="A - oldest",
        )
        rec_b = ChangeRecord(
            timestamp=700, agent="system", agent_id="", object_id="obj-b",
            change_type="content_update", before_snapshot_id="", after_snapshot_id="",
            reason="B - newest",
        )
        rec_c = ChangeRecord(
            timestamp=600, agent="system", agent_id="", object_id="obj-c",
            change_type="content_update", before_snapshot_id="", after_snapshot_id="",
            reason="C - middle",
        )

        hist_dir = historian._history_dir
        for rec, obj_id in [(rec_a, "obj-a"), (rec_b, "obj-b"), (rec_c, "obj-c")]:
            with open(hist_dir / f"{obj_id}.jsonl", "w", encoding="utf-8") as f:
                f.write(_json.dumps(_change_record_to_dict(rec)) + "\n")

        recent = historian.get_recent_changes(limit=10)
        assert len(recent) == 3
        assert recent[0].reason == "B - newest"
        assert recent[1].reason == "C - middle"
        assert recent[2].reason == "A - oldest"


class TestHistorianMultipleObjects:
    """Tests for multi-object separation."""

    def test_changes_for_different_objects_in_separate_files(
        self, historian: HistorianAgent
    ):
        """Changes for different objects are stored in separate JSONL files."""
        historian.record_change(
            object_id="obj-a", change_type="content_update", reason="Change A"
        )
        historian.record_change(
            object_id="obj-b", change_type="content_update", reason="Change B"
        )

        file_a = historian._history_dir / "obj-a.jsonl"
        file_b = historian._history_dir / "obj-b.jsonl"
        assert file_a.exists()
        assert file_b.exists()

        # Each file has exactly one record
        assert len(file_a.read_text(encoding="utf-8").strip().split("\n")) == 1
        assert len(file_b.read_text(encoding="utf-8").strip().split("\n")) == 1

    def test_get_change_history_is_object_specific(self, historian: HistorianAgent):
        """get_change_history() returns only records for the requested object."""
        historian.record_change(
            object_id="obj-a", change_type="content_update", reason="Change A"
        )
        historian.record_change(
            object_id="obj-b", change_type="content_update", reason="Change B"
        )

        history_a = historian.get_change_history("obj-a")
        assert len(history_a) == 1
        assert history_a[0].object_id == "obj-a"
        assert history_a[0].reason == "Change A"

        history_b = historian.get_change_history("obj-b")
        assert len(history_b) == 1
        assert history_b[0].object_id == "obj-b"
        assert history_b[0].reason == "Change B"


class TestHistorianAppendOnly:
    """Tests for append-only JSONL format."""

    def test_two_records_for_same_object_both_in_file(
        self, historian: HistorianAgent
    ):
        """Two records for the same object: both appear in the JSONL file (one per line)."""
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="First"
        )
        historian.record_change(
            object_id="obj-1", change_type="content_update", reason="Second"
        )

        filepath = historian._history_dir / "obj-1.jsonl"
        lines = filepath.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        record0 = json.loads(lines[0])
        record1 = json.loads(lines[1])
        assert record0["reason"] == "First"
        assert record1["reason"] == "Second"

    def test_append_does_not_overwrite(self, historian: HistorianAgent):
        """Appending a second record does not overwrite the first."""
        r1 = historian.record_change(
            object_id="obj-1", change_type="content_update", reason="First"
        )
        r2 = historian.record_change(
            object_id="obj-1", change_type="content_update", reason="Second"
        )

        history = historian.get_change_history("obj-1")
        assert len(history) == 2
        # Both records are readable
        reasons = {r.reason for r in history}
        assert "First" in reasons
        assert "Second" in reasons


class TestHistorianEventBusSubscription:
    """Tests for EventBus subscription behavior."""

    def test_historian_subscribes_on_init(self, wiki_paths: WikiPaths):
        """Historian subscribes to lifecycle.changed on init when event_bus is provided."""
        bus = EventBus()
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=bus)

        # Verify handler is registered by checking that emit creates a record
        bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": "obj-sub-test",
            "from": "created",
            "to": "processing",
            "reason": "Test subscription",
            "timestamp": 9999999,
        })

        history = historian.get_change_history("obj-sub-test")
        assert len(history) == 1

    def test_historian_without_event_bus_does_not_subscribe(
        self, wiki_paths: WikiPaths
    ):
        """Historian without event_bus does not crash and works for direct recording."""
        historian = HistorianAgent(wiki_paths=wiki_paths, event_bus=None)

        # Should still work for direct record_change
        record = historian.record_change(
            object_id="obj-1", change_type="content_update", reason="Direct"
        )
        assert record.object_id == "obj-1"

        history = historian.get_change_history("obj-1")
        assert len(history) == 1


class TestHistorianDirectoryCreation:
    """Tests for history directory creation."""

    def test_history_directory_created_on_init(self, wiki_paths: WikiPaths):
        """On init, .index/change_history/ directory is created."""
        historian = HistorianAgent(wiki_paths=wiki_paths)
        assert historian._history_dir.exists()
        assert historian._history_dir.is_dir()

    def test_history_directory_already_exists_is_fine(
        self, wiki_paths: WikiPaths
    ):
        """If the history directory already exists, init is idempotent."""
        hist_dir = wiki_paths.index / "change_history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        # Create a file in it to verify it's not wiped
        (hist_dir / "dummy.txt").write_text("hello")

        historian = HistorianAgent(wiki_paths=wiki_paths)
        assert (hist_dir / "dummy.txt").exists()
        assert (hist_dir / "dummy.txt").read_text() == "hello"


class TestHistorianEdgeCases:
    """Edge case tests for robustness."""

    def test_empty_object_id(self, historian: HistorianAgent):
        """record_change() works with empty object_id."""
        record = historian.record_change(
            object_id="", change_type="content_update", reason="No ID"
        )
        assert record.object_id == ""
        filepath = historian._history_dir / ".jsonl"
        assert filepath.exists()

    def test_special_characters_in_object_id(self, historian: HistorianAgent):
        """record_change() works with cross-platform-safe special characters in object_id."""
        # Use characters valid on both Windows and Unix: hyphens, dots, underscores,
        # CJK, and brackets. Avoid / : * ? < > | " which are invalid on Windows.
        obj_id = "obj-with.dots_and-mixed-中文-identifiers"
        record = historian.record_change(
            object_id=obj_id, change_type="content_update", reason="Special chars"
        )
        history = historian.get_change_history(obj_id)
        assert len(history) == 1
        assert history[0].object_id == obj_id

    def test_unicode_in_reason_and_details(self, historian: HistorianAgent):
        """record_change() handles unicode in reason and details."""
        record = historian.record_change(
            object_id="obj-unicode",
            change_type="content_update",
            reason="中文原因",
            details={"描述": "日本語の説明"},
        )
        history = historian.get_change_history("obj-unicode")
        assert len(history) == 1
        assert history[0].reason == "中文原因"
        assert history[0].details == {"描述": "日本語の説明"}

    def test_large_details_dict(self, historian: HistorianAgent):
        """record_change() handles a large details dict."""
        large_details = {f"key_{i}": f"value_{i}" for i in range(100)}
        record = historian.record_change(
            object_id="obj-large",
            change_type="content_update",
            reason="Large details",
            details=large_details,
        )
        history = historian.get_change_history("obj-large")
        assert len(history) == 1
        assert history[0].details == large_details
