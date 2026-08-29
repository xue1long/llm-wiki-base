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
import sys
import time
from hashlib import sha256


def compute_payload_hash(payload: dict) -> str:
    """Canonical payload hash — sha256 of canonical JSON (sorted keys)."""
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class _EventFileLock:
    """Cross-process exclusive lock around the check-then-write window.

    The lock file (``{index}/knowledge_graph/events.lock``) is a sibling of
    ``events.jsonl``. POSIX uses ``fcntl.flock(fd, LOCK_EX)``; Windows uses
    ``msvcrt.locking(fd, LK_LOCK, 1)`` — a byte-range lock at the current
    file offset, so the fd is seeked to 0 before both locking and unlocking
    to keep the locked range stable. ``LK_LOCK`` retries for up to ~10s
    before raising, giving blocking semantics. Separate fds to the same
    lock file contend with each other (flock and Windows byte-range locks
    are enforced per open file description), so this serialises threads
    within a process *and* processes on the same index path.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = Path(lock_path)
        self._fh = None

    def __enter__(self) -> "_EventFileLock":
        self._fh = open(self._lock_path, "a+b")
        self._fh.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._fh.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


class EventStore(ABC):
    """Structured event storage for knowledge graph events.

    Events are the source of truth for the knowledge graph.
    Snapshots are rebuilt from events.
    """

    @abstractmethod
    def append(self, stream_id: str, event_type: str, payload: dict) -> int:
        """Append an event. Returns the event version number."""
        ...

    def append_event(
        self,
        stream_id: str,
        event_type: str,
        payload: dict,
        *,
        operation_id: str,
        payload_hash: str | None = None,
    ) -> dict:
        """Idempotent event append keyed by *operation_id* (additive to append()).

        Returns:
            ``{"status": "ok", "event": {...}}`` — first write.
            ``{"status": "duplicate", "event": {...}}`` — idempotent replay
            (same operation_id + same payload_hash); the original event is returned.
            ``{"status": "version_conflict", "event": {...}, "stored_payload_hash": ...}``
            — same operation_id but different payload_hash; nothing is written.

        Note (fail-closed default): backends that do not override this
        method (e.g. ``PostgresEventStore``) inherit this default and
        fail closed with ``NotImplementedError`` — idempotent append is
        only available where explicitly implemented (currently
        ``JSONLEventStore``). Callers must treat a raised
        ``NotImplementedError`` as "append not supported", never as a
        silent non-idempotent write.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement append_event"
        )

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
    Thread-safe via append-only writes; the idempotent
    :meth:`append_event` additionally serialises its check-then-write
    window with a cross-process file lock (``events.lock``).

    File: {index_path}/knowledge_graph/events.jsonl
    Format: one JSON object per line
    """

    def __init__(self, index_path: Path) -> None:
        self._events_path = Path(index_path) / "knowledge_graph" / "events.jsonl"
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._events_path.parent / "events.lock"
        self._version_counter = self._load_version()
        self._operation_index: dict[str, dict] | None = None

    def _load_version(self) -> int:
        """Count existing lines to determine current version."""
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                return sum(1 for _ in fh)
        except (FileNotFoundError, OSError):
            return 0

    def _load_operation_index(self) -> dict[str, dict]:
        """Lazily scan the file for operation_id-keyed events.

        The file is authoritative for cold-start replay; the in-memory index is
        a session cache updated on new writes.
        """
        if self._operation_index is None:
            index: dict[str, dict] = {}
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
                        op_id = event.get("operation_id")
                        if op_id:
                            index[op_id] = event
            except (FileNotFoundError, OSError):
                pass
            self._operation_index = index
        return self._operation_index

    def append_event(
        self,
        stream_id: str,
        event_type: str,
        payload: dict,
        *,
        operation_id: str,
        payload_hash: str | None = None,
    ) -> dict:
        """Idempotent event append keyed by *operation_id*.

        Replaying the same operation_id with the same payload returns the
        original event (``duplicate``); a different payload_hash under the same
        operation_id fails closed with ``version_conflict`` and writes nothing.

        Concurrency: the operation-index lookup and the file append are
        serialised by a cross-process exclusive lock on ``events.lock``
        (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows). The
        in-memory index is refreshed from disk under the lock, so two
        threads or two processes appending the same operation_id
        concurrently produce exactly one ``ok`` and one ``duplicate``.
        """
        if payload_hash is None:
            payload_hash = compute_payload_hash(payload)

        # Fast path: the session index may already know this operation —
        # entries are only ever added, so a hit is authoritative.
        index = self._load_operation_index()
        existing = index.get(operation_id)
        if existing is not None:
            return self._existing_operation_result(
                existing, event_type, payload, stream_id, operation_id, payload_hash
            )

        # Slow path: re-check under the cross-process lock, refreshing the
        # in-memory index from disk so a concurrent writer's event is
        # visible before we decide to append.
        with _EventFileLock(self._lock_path):
            self._operation_index = None
            index = self._load_operation_index()
            existing = index.get(operation_id)
            if existing is not None:
                return self._existing_operation_result(
                    existing, event_type, payload, stream_id, operation_id, payload_hash
                )

            self._version_counter += 1
            event = {
                "action": event_type,
                **payload,
                "timestamp": int(time.time() * 1000),
                "stream_id": stream_id,
                "event_version": self._version_counter,
                "operation_id": operation_id,
                "payload_hash": payload_hash,
            }
            line = json.dumps(event, ensure_ascii=False) + "\n"
            with open(self._events_path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
            index[operation_id] = event
            return {"status": "ok", "event": event}

    def _existing_operation_result(
        self,
        existing: dict,
        event_type: str,
        payload: dict,
        stream_id: str,
        operation_id: str,
        payload_hash: str,
    ) -> dict:
        """Return ``duplicate`` / ``version_conflict`` for a recorded operation."""
        if existing.get("payload_hash") != payload_hash:
            return {
                "status": "version_conflict",
                "event": {
                    "action": event_type,
                    **payload,
                    "timestamp": int(time.time() * 1000),
                    "stream_id": stream_id,
                    "operation_id": operation_id,
                    "payload_hash": payload_hash,
                },
                "stored_payload_hash": existing.get("payload_hash"),
            }
        return {"status": "duplicate", "event": existing}

    def append(self, stream_id: str, event_type: str, payload: dict) -> int:
        """Append event as JSON line. Increment and return version.

        Event format is compatible with GraphBuilder._apply_event():
        ``action`` maps from *event_type*, and *payload* keys are spread
        at the top level so that ``node``/``edge``/``node_id``/``edge_id``
        are directly accessible.
        """
        self._version_counter += 1
        version = self._version_counter
        event = {
            "action": event_type,
            **payload,
            "timestamp": int(time.time() * 1000),
            "stream_id": stream_id,
            "event_version": version,
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
                    ts = event.get("timestamp", 0)
                    if isinstance(ts, (int, float)) and ts >= since_timestamp:
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

    ``append_event``: inherits the ABC default (raises ``NotImplementedError``,
    fail-closed). A real Postgres implementation of idempotent
    ``operation_id``-keyed append is deferred and out of scope for this plan
    (see plan Task 3 OPEN-2 / progress.md Known Limitations); the Postgres
    backend is configuration-only — no production caller in this plan
    exercises it. Callers must treat the raised ``NotImplementedError`` as
    "append not supported", never as a silent non-idempotent write.
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
