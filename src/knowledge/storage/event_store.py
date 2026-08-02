"""Structured event storage for knowledge graph events.

Events are the source of truth for the knowledge graph.
Snapshots are rebuilt from events.

Backends:
    JSONLEventStore  — append-only JSONL file (default)
    PostgresEventStore — PostgreSQL with structured schema (multi-instance)
"""

from abc import ABC, abstractmethod
from pathlib import Path
import json
import time


class EventStore(ABC):
    """Structured event storage for knowledge graph events.

    Events are the source of truth for the knowledge graph.
    Snapshots are rebuilt from events.
    """

    @abstractmethod
    def append(self, stream_id: str, event_type: str, payload: dict) -> int:
        """Append an event. Returns the event version number."""
        ...

    @abstractmethod
    def read_stream(self, stream_id: str, since_version: int = 0) -> list[dict]:
        """Read events for a stream, optionally since a specific version."""
        ...

    @abstractmethod
    def read_all(self, since_timestamp: int = 0) -> list[dict]:
        """Read all events since a timestamp."""
        ...

    @abstractmethod
    def count(self, stream_id: str | None = None) -> int:
        """Count events. If stream_id is None, count all."""
        ...


class JSONLEventStore(EventStore):
    """Thin wrapper over the existing events.jsonl file from Phase 2.

    Default backend. Same behavior as Phase 2-4 GraphBuilder.
    Thread-safe via append-only writes.

    File: {index_path}/knowledge_graph/events.jsonl
    Format: one JSON object per line
    """

    def __init__(self, index_path: Path) -> None:
        self._events_path = Path(index_path) / "knowledge_graph" / "events.jsonl"
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._version_counter = self._load_version()

    def _load_version(self) -> int:
        """Count existing lines to determine current version."""
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                return sum(1 for _ in fh)
        except (FileNotFoundError, OSError):
            return 0

    def append(self, stream_id: str, event_type: str, payload: dict) -> int:
        """Append event as JSON line. Increment and return version."""
        self._version_counter += 1
        version = self._version_counter
        event = {
            "stream_id": stream_id,
            "event_type": event_type,
            "event_version": version,
            "payload": payload,
            "occurred_at": int(time.time() * 1000),
        }
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with open(self._events_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return version

    def read_stream(self, stream_id: str, since_version: int = 0) -> list[dict]:
        """Read events for a stream by scanning all lines."""
        events: list[dict] = []
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        event = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if (
                        event.get("stream_id") == stream_id
                        and event.get("event_version", 0) > since_version
                    ):
                        events.append(event)
        except (FileNotFoundError, OSError):
            pass
        return events

    def read_all(self, since_timestamp: int = 0) -> list[dict]:
        """Read all events since a timestamp."""
        events: list[dict] = []
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        event = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if "occurred_at" in event and event["occurred_at"] >= since_timestamp:
                        events.append(event)
        except (FileNotFoundError, OSError):
            pass
        return events

    def count(self, stream_id: str | None = None) -> int:
        """Count total events or events for a specific stream."""
        total = 0
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        event = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    if stream_id is None:
                        total += 1
                    elif event.get("stream_id") == stream_id:
                        total += 1
        except (FileNotFoundError, OSError):
            pass
        return total

    def get_events_path(self) -> Path:
        """Return path to events.jsonl (for GraphBuilder compatibility)."""
        return self._events_path


class PostgresEventStore(EventStore):
    """PostgreSQL-backed event store with structured schema.

    Schema:
        CREATE TABLE IF NOT EXISTS events (
            id BIGSERIAL PRIMARY KEY,
            stream_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_version INTEGER NOT NULL,
            payload JSONB NOT NULL,
            occurred_at BIGINT NOT NULL,
            recorded_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
        );
        CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream_id, event_version);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);

    Used when storage.event_store.backend = "postgresql".
    Requires psycopg2 or asyncpg to be installed separately.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn = None

    def _ensure_connection(self):
        """Lazily establish a database connection."""
        if self._conn is not None:
            return
        # Lazy import — psycopg2 is not a project dependency
        import psycopg2
        self._conn = psycopg2.connect(self._database_url)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        cur = self._conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id BIGSERIAL PRIMARY KEY,
                    stream_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_version INTEGER NOT NULL,
                    payload JSONB NOT NULL,
                    occurred_at BIGINT NOT NULL,
                    recorded_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_stream
                ON events(stream_id, event_version)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(event_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_occurred
                ON events(occurred_at)
            """)
            self._conn.commit()
        finally:
            cur.close()

    def append(self, stream_id: str, event_type: str, payload: dict) -> int:
        """Insert event into PostgreSQL. Returns the event version."""
        self._ensure_connection()
        cur = self._conn.cursor()
        try:
            occurred_at = int(time.time() * 1000)
            cur.execute(
                """
                INSERT INTO events (stream_id, event_type, event_version, payload, occurred_at)
                VALUES (%s, %s, (
                    SELECT COALESCE(MAX(event_version), 0) + 1
                    FROM events
                    WHERE stream_id = %s
                ), %s, %s)
                RETURNING event_version
                """,
                (stream_id, event_type, stream_id, json.dumps(payload), occurred_at),
            )
            version = cur.fetchone()[0]
            self._conn.commit()
            return version
        finally:
            cur.close()

    def read_stream(self, stream_id: str, since_version: int = 0) -> list[dict]:
        """Read events for a stream since a specific version."""
        self._ensure_connection()
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                SELECT stream_id, event_type, event_version, payload, occurred_at
                FROM events
                WHERE stream_id = %s AND event_version > %s
                ORDER BY event_version
                """,
                (stream_id, since_version),
            )
            rows = cur.fetchall()
            return [
                {
                    "stream_id": row[0],
                    "event_type": row[1],
                    "event_version": row[2],
                    "payload": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
                    "occurred_at": row[4],
                }
                for row in rows
            ]
        finally:
            cur.close()

    def read_all(self, since_timestamp: int = 0) -> list[dict]:
        """Read all events since a timestamp."""
        self._ensure_connection()
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                SELECT stream_id, event_type, event_version, payload, occurred_at
                FROM events
                WHERE occurred_at >= %s
                ORDER BY occurred_at
                """,
                (since_timestamp,),
            )
            rows = cur.fetchall()
            return [
                {
                    "stream_id": row[0],
                    "event_type": row[1],
                    "event_version": row[2],
                    "payload": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
                    "occurred_at": row[4],
                }
                for row in rows
            ]
        finally:
            cur.close()

    def count(self, stream_id: str | None = None) -> int:
        """Count events, optionally filtered by stream."""
        self._ensure_connection()
        cur = self._conn.cursor()
        try:
            if stream_id is None:
                cur.execute("SELECT COUNT(*) FROM events")
            else:
                cur.execute(
                    "SELECT COUNT(*) FROM events WHERE stream_id = %s",
                    (stream_id,),
                )
            return cur.fetchone()[0]
        finally:
            cur.close()
