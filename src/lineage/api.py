from __future__ import annotations

import sqlite3
import uuid
import hashlib
from pathlib import Path

from .types import LineageHealth, RawScanResult, RawSourceChange


_TRANSITIONS = {
    "discovered": {"ingested", "blocked", "failed", "deleted"},
    "ingested": {"kc_published", "blocked", "failed", "deleted"},
    "kc_published": {"wiki_committed", "blocked", "failed", "deleted"},
    "wiki_committed": {"book_pending", "blocked", "failed", "deleted"},
    "book_pending": {"book_compiled", "blocked", "failed", "deleted"},
    "book_compiled": {"book_pending", "blocked", "deleted"},
    "blocked": {"ingested", "deleted"},
    "failed": {"ingested", "deleted"},
    "deleted": set(),
}


class LineageStore:
    def __init__(self, connection: sqlite3.Connection, project_root: Path):
        self._db = connection
        self._project_root = Path(project_root)

    @classmethod
    def open(cls, project_root: Path) -> "LineageStore":
        db_path = Path(project_root) / ".index" / "lineage" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_kind TEXT NOT NULL,
                artifact_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifact_sources (
                artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                PRIMARY KEY (artifact_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS source_reasons (
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                reason TEXT NOT NULL,
                PRIMARY KEY (source_id, reason)
            );
            CREATE TABLE IF NOT EXISTS build_runs (
                run_id TEXT PRIMARY KEY,
                expected_source_ids TEXT NOT NULL,
                input_snapshot TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS build_members (
                run_id TEXT NOT NULL REFERENCES build_runs(run_id),
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                chapter_id TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (run_id, source_id, chapter_id)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                event_key TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS build_lease (
                lease_id INTEGER PRIMARY KEY CHECK (lease_id = 1),
                run_id TEXT NOT NULL
            );
            """
        )
        db.commit()
        return cls(db, Path(project_root))

    def register_source(self, source_id: str, source_path: str,
                        source_hash: str, status: str) -> None:
        self._db.execute(
            """INSERT INTO sources(source_id, source_path, source_hash, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                 source_path=excluded.source_path,
                 source_hash=excluded.source_hash,
                 status=excluded.status""",
            (source_id, source_path, source_hash, status),
        )
        self._db.commit()

    def source(self, source_id: str) -> dict:
        row = self._db.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return dict(row)

    def source_id_for_path(self, source_path: str) -> str | None:
        row = self._db.execute(
            "SELECT source_id FROM sources WHERE source_path = ?", (source_path,)
        ).fetchone()
        return None if row is None else str(row[0])

    def transition_source(self, source_id: str, expected: str, new: str,
                          reasons: tuple[str, ...] = ()) -> None:
        current = self.source(source_id)["status"]
        if current != expected or new not in _TRANSITIONS.get(expected, set()):
            raise ValueError(f"illegal source transition: {current} -> {new}")
        with self._db:
            self._db.execute(
                "UPDATE sources SET status = ? WHERE source_id = ?", (new, source_id)
            )
            self._db.executemany(
                "INSERT OR IGNORE INTO source_reasons(source_id, reason) VALUES (?, ?)",
                ((source_id, reason) for reason in reasons),
            )

    def source_reasons(self, source_id: str) -> tuple[str, ...]:
        rows = self._db.execute(
            "SELECT reason FROM source_reasons WHERE source_id = ? ORDER BY reason",
            (source_id,),
        )
        return tuple(row[0] for row in rows)

    def discover_raw_sources(self, raw_dir: Path | None = None) -> RawScanResult:
        root = Path(raw_dir) if raw_dir is not None else self._project_root / "raw" / "sources"
        if not root.is_dir():
            return RawScanResult(False, ())
        try:
            files = sorted(p for p in root.rglob("*") if p.is_file())
            rows = self._db.execute("SELECT source_id, source_path, source_hash, status FROM sources")
            known = {row["source_path"]: row for row in rows}
            changes: list[RawSourceChange] = []
            for path in files:
                rel = path.relative_to(self._project_root).as_posix()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                row = known.get(rel)
                if row is None:
                    source_id = "src-" + hashlib.sha256(rel.encode()).hexdigest()[:32]
                    self.register_source(source_id, rel, digest, "discovered")
                    changes.append(RawSourceChange(source_id, rel, digest, "discovered"))
                elif row["source_hash"] != digest:
                    self._db.execute(
                        "UPDATE sources SET source_hash = ?, status = 'stale' WHERE source_id = ?",
                        (digest, row["source_id"]),
                    )
                    self._db.commit()
                    changes.append(RawSourceChange(row["source_id"], rel, digest, "stale"))
            return RawScanResult(True, tuple(changes))
        except OSError:
            return RawScanResult(False, ())

    def record_raw_assessment(self, source_id: str, decision: str,
                              reasons: tuple[str, ...] = ()) -> None:
        self.source(source_id)
        with self._db:
            self._db.execute("UPDATE sources SET status = ? WHERE source_id = ?",
                             (decision, source_id))
            self._db.executemany(
                "INSERT OR IGNORE INTO source_reasons(source_id, reason) VALUES (?, ?)",
                ((source_id, reason) for reason in reasons),
            )

    def mark_raw_ingested(self, source_path: str) -> str | None:
        source_id = self.source_id_for_path(source_path)
        if source_id is None:
            return None
        self.record_raw_assessment(source_id, "ingested", ("pipeline_committed",))
        return source_id

    def record_raw_tombstone(self, source_id: str, source_path: str,
                             observed_hash: str | None = None, *,
                             explicit: bool = False) -> None:
        if not explicit:
            raise ValueError("raw deletion requires explicit confirmation")
        source = self.source(source_id)
        if source["source_path"] != source_path:
            raise ValueError("source path does not match persisted identity")
        if observed_hash is not None and source["source_hash"] != observed_hash:
            raise ValueError("tombstone hash does not match persisted source")
        self._db.execute("UPDATE sources SET status = 'deleted' WHERE source_id = ?",
                         (source_id,))
        self._db.commit()

    def create_build_run(self, expected_source_ids: tuple[str, ...],
                         input_snapshot: str) -> str:
        run_id = uuid.uuid4().hex
        self._db.execute(
            "INSERT INTO build_runs(run_id, expected_source_ids, input_snapshot) VALUES (?, ?, ?)",
            (run_id, "\n".join(sorted(expected_source_ids)), input_snapshot),
        )
        self._db.commit()
        return run_id

    def record_build_member(self, run_id: str, source_id: str,
                            chapter_id: str, status: str) -> None:
        if self._db.execute(
            "SELECT 1 FROM build_runs WHERE run_id = ?", (run_id,)
        ).fetchone() is None:
            raise ValueError(f"unknown build run: {run_id}")
        if self._db.execute(
            "SELECT 1 FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone() is None:
            raise ValueError(f"unknown source: {source_id}")
        self._db.execute(
            """INSERT INTO build_members(run_id, source_id, chapter_id, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(run_id, source_id, chapter_id) DO UPDATE SET status=excluded.status""",
            (run_id, source_id, chapter_id, status),
        )
        self._db.commit()

    def build_members(self, run_id: str) -> tuple[tuple[str, str, str], ...]:
        rows = self._db.execute(
            "SELECT source_id, chapter_id, status FROM build_members WHERE run_id = ? ORDER BY source_id, chapter_id",
            (run_id,),
        )
        return tuple(tuple(row) for row in rows)

    def enqueue_outbox(self, event_key: str, event_type: str,
                       source_id: str) -> bool:
        cur = self._db.execute(
            "INSERT OR IGNORE INTO outbox(event_key, event_type, source_id) VALUES (?, ?, ?)",
            (event_key, event_type, source_id),
        )
        self._db.commit()
        return cur.rowcount == 1

    def pending_outbox(self) -> tuple[tuple[str, str, str], ...]:
        rows = self._db.execute(
            "SELECT event_key, event_type, source_id FROM outbox WHERE delivered = 0 ORDER BY event_key"
        )
        return tuple(tuple(row) for row in rows)

    def replay_outbox(self) -> tuple[str, ...]:
        pending = self.pending_outbox()
        with self._db:
            self._db.executemany(
                "UPDATE outbox SET delivered = 1 WHERE event_key = ?",
                ((event_key,) for event_key, _event_type, _source_id in pending),
            )
        return tuple(event_key for event_key, _event_type, _source_id in pending)

    def build_snapshot_is_current(self, run_id: str) -> bool:
        row = self._db.execute(
            "SELECT expected_source_ids, input_snapshot FROM build_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        expected = tuple(item for item in row[0].split("\n") if item)
        snapshot = dict(
            item.split(":", 1) for item in row[1].split("\n") if ":" in item
        )
        return self.snapshot_matches(expected, row[1])

    def snapshot_matches(self, expected_source_ids: tuple[str, ...], input_snapshot: str) -> bool:
        snapshot = dict(
            item.split(":", 1) for item in input_snapshot.split("\n") if ":" in item
        )
        current = {
            source["source_id"]: source["source_hash"]
            for source in self.sources()
            if source["source_id"] in expected_source_ids
        }
        return current == snapshot and set(current) == set(expected_source_ids)

    def acquire_build_lease(self, run_id: str) -> bool:
        try:
            with self._db:
                self._db.execute("INSERT INTO build_lease(lease_id, run_id) VALUES (1, ?)", (run_id,))
            return True
        except sqlite3.IntegrityError:
            return False

    def release_build_lease(self, run_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM build_lease WHERE lease_id = 1 AND run_id = ?", (run_id,))

    def link_artifact(self, artifact_kind: str, artifact_id: str,
                      source_ids: tuple[str, ...], path: str,
                      content_hash: str, status: str) -> None:
        with self._db:
            self._db.execute(
                """INSERT INTO artifacts(artifact_kind, artifact_id, path,
                   content_hash, status) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(artifact_id) DO UPDATE SET
                     artifact_kind=excluded.artifact_kind, path=excluded.path,
                     content_hash=excluded.content_hash, status=excluded.status""",
                (artifact_kind, artifact_id, path, content_hash, status),
            )
            self._db.execute(
                "DELETE FROM artifact_sources WHERE artifact_id = ?", (artifact_id,)
            )
            self._db.executemany(
                "INSERT INTO artifact_sources(artifact_id, source_id) VALUES (?, ?)",
                ((artifact_id, source_id) for source_id in source_ids),
            )

    def record_wiki_commit(self, wiki_page_id: str,
                           source_ids: tuple[str, ...], path: str,
                           content_hash: str) -> None:
        self.link_artifact("wiki", wiki_page_id, source_ids, path,
                           content_hash, "committed")

    def record_kc_commit(self, bundle_id: str, source_ids: tuple[str, ...],
                         path: str, content_hash: str,
                         publication_version: int) -> None:
        del publication_version
        self.link_artifact("kc", bundle_id, source_ids, path,
                           content_hash, "committed")

    def artifact_sources(self, artifact_id: str) -> tuple[str, ...]:
        rows = self._db.execute(
            "SELECT source_id FROM artifact_sources WHERE artifact_id = ? ORDER BY source_id",
            (artifact_id,),
        )
        return tuple(row[0] for row in rows)

    def sources(self, *, status: str | None = None) -> tuple[dict, ...]:
        query = "SELECT * FROM sources"
        args: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            args = (status,)
        query += " ORDER BY source_id"
        return tuple(dict(row) for row in self._db.execute(query, args))

    def artifacts(self, *, artifact_kind: str | None = None,
                  status: str | None = None) -> tuple[dict, ...]:
        clauses: list[str] = []
        args: list[str] = []
        if artifact_kind is not None:
            clauses.append("artifact_kind = ?")
            args.append(artifact_kind)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        query = "SELECT * FROM artifacts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY artifact_id"
        return tuple(dict(row) for row in self._db.execute(query, args))

    def artifacts_for_source(self, source_id: str, *, artifact_kind: str) -> tuple[str, ...]:
        rows = self._db.execute(
            """SELECT a.artifact_id FROM artifacts a
               JOIN artifact_sources r ON r.artifact_id = a.artifact_id
               WHERE r.source_id = ? AND a.artifact_kind = ? AND a.status = 'committed'
               ORDER BY a.artifact_id""",
            (source_id, artifact_kind),
        )
        return tuple(row[0] for row in rows)

    def health(self) -> LineageHealth:
        integrity = self._db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        orphan = self._db.execute(
            """SELECT COUNT(*) FROM artifact_sources rel
               LEFT JOIN artifacts a ON a.artifact_id = rel.artifact_id
               LEFT JOIN sources s ON s.source_id = rel.source_id
               WHERE a.artifact_id IS NULL OR s.source_id IS NULL"""
        ).fetchone()[0]
        pending = self._db.execute("SELECT COUNT(*) FROM outbox WHERE delivered = 0").fetchone()[0]
        valid = set(_TRANSITIONS) 
        invalid = self._db.execute(
            "SELECT COUNT(*) FROM sources WHERE status NOT IN (%s)" % ",".join("?" * len(valid)),
            tuple(valid),
        ).fetchone()[0]
        missing = 0
        mismatches = 0
        for artifact in self.artifacts():
            path = self._project_root / artifact["path"]
            if not path.is_file():
                missing += 1
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                missing += 1
                continue
            if digest != artifact["content_hash"]:
                mismatches += 1
        return LineageHealth(integrity_ok=integrity, orphan_links=orphan,
                             pending_outbox=pending, invalid_statuses=invalid,
                             missing_artifacts=missing, hash_mismatches=mismatches)
