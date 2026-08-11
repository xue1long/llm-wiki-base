"""HistorianAgent — structured change history for all KnowledgeObjects.

Records changes as append-only JSONL files under .index/change_history/.
Subscribes to EventBus lifecycle.changed events (emitted by LifecycleEngine)
and supports direct recording for non-lifecycle changes.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.events.event_bus import EventBus
from src.wiki.core.paths import WikiPaths


@dataclass
class ChangeRecord:
    """A single change record stored in .index/change_history/{object_id}.jsonl"""

    timestamp: int           # Unix ms
    agent: str               # Agent type that made the change
    agent_id: str            # Specific agent instance ID
    object_id: str           # Target object
    change_type: str         # "lifecycle_transition" | "content_update" | "relation_change" | "provenance_update"
    before_snapshot_id: str  # VersionManager snapshot ID before change
    after_snapshot_id: str   # VersionManager snapshot ID after change
    reason: str              # Human-readable reason for the change
    details: dict = field(default_factory=dict)  # Additional change-specific data


def _change_record_to_dict(record: ChangeRecord) -> dict:
    """Serialize a ChangeRecord to a JSON-safe dict."""
    return asdict(record)


def _dict_to_change_record(d: dict) -> ChangeRecord:
    """Deserialize a dict back to a ChangeRecord."""
    return ChangeRecord(
        timestamp=d.get("timestamp", 0),
        agent=d.get("agent", ""),
        agent_id=d.get("agent_id", ""),
        object_id=d.get("object_id", ""),
        change_type=d.get("change_type", ""),
        before_snapshot_id=d.get("before_snapshot_id", ""),
        after_snapshot_id=d.get("after_snapshot_id", ""),
        reason=d.get("reason", ""),
        details=d.get("details", {}),
    )


class HistorianAgent:
    """Records structured change history for all KnowledgeObjects.

    Architecture (per audit M17 fix):
    - Subscribes to EventBus for lifecycle.changed (emitted by LifecycleEngine)
    - LifecycleEngine emits events, pipeline event logger writes wiki/log.md,
      Historian subscribes to SAME events and writes structured change records.
    - ONE event, multiple consumers. No duplicate log writing.

    Storage: .index/change_history/{object_id}.jsonl — append-only JSONL
    """

    def __init__(self, wiki_paths: WikiPaths, event_bus: EventBus = None):
        self._paths = wiki_paths
        self._history_dir = wiki_paths.index / "change_history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._event_bus = event_bus
        if self._event_bus:
            self._subscribe()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def _subscribe(self):
        """Subscribe to lifecycle events from EventBus.

        Listens for "lifecycle.changed" — the event name emitted by
        LifecycleEngine.transition() in src/knowledge/core/lifecycle.py.
        """
        self._event_bus.on("lifecycle.changed", self._on_lifecycle_changed)

    def _on_lifecycle_changed(self, event: dict):
        """Handle a lifecycle change event, writing a structured ChangeRecord.

        The event dict (emitted by LifecycleEngine) contains:
            event, object_id, from, to, reason, timestamp
        """
        record = ChangeRecord(
            timestamp=event.get("timestamp", int(time.time() * 1000)),
            agent=event.get("agent", "lifecycle_engine"),
            agent_id=event.get("agent_id", ""),
            object_id=event.get("object_id", ""),
            change_type="lifecycle_transition",
            before_snapshot_id=event.get("from", ""),
            after_snapshot_id=event.get("to", ""),
            reason=event.get("reason", ""),
            details={
                "old_state": event.get("from", ""),
                "new_state": event.get("to", ""),
            },
        )
        self._append_record(record)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_change(
        self,
        object_id: str,
        change_type: str,
        reason: str,
        agent: str = "system",
        agent_id: str = "",
        before_snapshot_id: str = "",
        after_snapshot_id: str = "",
        details: dict = None,
    ) -> ChangeRecord:
        """Directly record a change (not via EventBus).

        Used for non-lifecycle changes (content updates, relation changes, etc.)
        """
        record = ChangeRecord(
            timestamp=int(time.time() * 1000),
            agent=agent,
            agent_id=agent_id,
            object_id=object_id,
            change_type=change_type,
            before_snapshot_id=before_snapshot_id,
            after_snapshot_id=after_snapshot_id,
            reason=reason,
            details=details or {},
        )
        self._append_record(record)
        return record

    def get_change_history(self, object_id: str) -> list[ChangeRecord]:
        """Return all change records for an object, newest first."""
        filepath = self._history_dir / f"{object_id}.jsonl"
        if not filepath.exists():
            return []
        return self._read_records_from_file(filepath)

    def get_changes_by_agent(self, agent_type: str, since: int = 0) -> list[ChangeRecord]:
        """Return all changes by a specific agent type since a timestamp.

        Scans all .jsonl files (can be slow for large histories).
        """
        results: list[ChangeRecord] = []
        for filepath in self._history_dir.glob("*.jsonl"):
            for record in self._read_records_from_file(filepath):
                if record.agent == agent_type and record.timestamp >= since:
                    results.append(record)
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results

    def get_recent_changes(self, limit: int = 50) -> list[ChangeRecord]:
        """Return the most recent changes across all objects."""
        all_records: list[ChangeRecord] = []
        for filepath in self._history_dir.glob("*.jsonl"):
            all_records.extend(self._read_records_from_file(filepath))
        all_records.sort(key=lambda r: r.timestamp, reverse=True)
        return all_records[:limit]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_records_from_file(self, filepath: Path) -> list[ChangeRecord]:
        """Read all ChangeRecords from a JSONL file, newest first."""
        records: list[ChangeRecord] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(_dict_to_change_record(json.loads(line)))
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records

    def _append_record(self, record: ChangeRecord) -> None:
        """Append a single ChangeRecord to its object's JSONL file."""
        filepath = self._history_dir / f"{record.object_id}.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(_change_record_to_dict(record), ensure_ascii=False) + "\n")
