from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
import hashlib
from pathlib import Path
from typing import Iterable

from .types import LineageHealth, RawScanResult, RawSourceChange

log = logging.getLogger(__name__)


def _safe_insert_artifact_sources(
    db: sqlite3.Connection,
    artifact_id: str,
    source_ids: Iterable[str],
) -> list[tuple[str, str]]:
    """Write source_ids into ``artifact_sources`` with dedup + orphan tolerance.

    Returns ``[(source_id, error_msg), ...]`` for the ones that were
    skipped due to FK orphan or duplicate. The caller decides whether to
    log / clear pending state based on this list.

    Plan: docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
    """
    seen: set[str] = set()
    errors: list[tuple[str, str]] = []
    for sid in source_ids:
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            db.execute(
                "INSERT OR IGNORE INTO artifact_sources"
                "(artifact_id, source_id) VALUES (?, ?)",
                (artifact_id, sid),
            )
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "FOREIGN KEY constraint" in msg:
                log.warning(
                    "orphan source_id skipped: %s/%s", artifact_id, sid,
                )
                errors.append((sid, "FK violation"))
            elif "UNIQUE constraint" in msg:
                # INSERT OR IGNORE should swallow this, but record defensively.
                errors.append((sid, "UNIQUE violation"))
            else:
                raise
    return errors


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


def _hash_matches(path: Path, expected: str) -> bool:
    """Match current bytes and legacy LF-normalized text hashes."""
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == expected:
            return True
        text = raw.decode("utf-8").replace("\r\n", "\n")
        return hashlib.sha256(text.encode("utf-8")).hexdigest() == expected
    except (OSError, UnicodeDecodeError):
        return False


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
                input_snapshot TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                wiki_snapshot TEXT NOT NULL DEFAULT '',
                book_id TEXT NOT NULL DEFAULT '',
                artifact_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS build_members (
                run_id TEXT NOT NULL REFERENCES build_runs(run_id),
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                chapter_id TEXT NOT NULL,
                status TEXT NOT NULL,
                input_hash TEXT NOT NULL DEFAULT '',
                output_hash TEXT NOT NULL DEFAULT '',
                output_path TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS pending_wiki_commits (
                wiki_page_id TEXT PRIMARY KEY, source_ids TEXT NOT NULL,
                path TEXT NOT NULL, content_hash TEXT NOT NULL
            );
            """
        )
        cls._ensure_columns(db, "build_runs", {
            "status": "TEXT NOT NULL DEFAULT 'running'",
            "wiki_snapshot": "TEXT NOT NULL DEFAULT ''",
            "book_id": "TEXT NOT NULL DEFAULT ''",
            "artifact_id": "TEXT NOT NULL DEFAULT ''",
        })
        cls._ensure_columns(db, "build_members", {
            "input_hash": "TEXT NOT NULL DEFAULT ''",
            "output_hash": "TEXT NOT NULL DEFAULT ''",
            "output_path": "TEXT NOT NULL DEFAULT ''",
        })
        db.commit()
        root = Path(project_root)
        cls._recover_pending(db, root)
        cls._recover_book_releases(db, root)
        return cls(db, root)

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {
            str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")
        }
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _recover_pending(db: sqlite3.Connection, root: Path) -> None:
        """Restore pending_wiki_commits into artifact_sources.

        Decision table:
        - file missing or hash mismatched → skip (pending stays for ops)
        - INSERT succeeds → page_id in pending_deletions
        - INSERT partial-fails (FK orphans swallowed) → page_id in
          pending_deletions AND write to recovery_errors.log
        - helper raises non-IntegrityError → skip (pending stays)

        The DELETE for pending_wiki_commits is conditional on the row
        having reached the artifacts/artifact_sources tables, so a row
        that errored out is preserved for an operator to inspect.

        Plan: docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
        """
        rows = db.execute(
            "SELECT wiki_page_id, source_ids, path, content_hash "
            "FROM pending_wiki_commits"
        ).fetchall()

        recovery_log = root / ".index" / "lineage" / "recovery_errors.log"
        pending_deletions: list[str] = []  # only successful page_ids

        for page_id, source_ids, path, expected in rows:
            try:
                target = root / path
                if not target.is_file() or not _hash_matches(target, expected):
                    continue  # skip — pending stays
                ids = list(x for x in source_ids.split("\n") if x)

                db.execute(
                    "INSERT OR REPLACE INTO artifacts"
                    "(artifact_kind, artifact_id, path, content_hash, status) "
                    "VALUES ('wiki', ?, ?, ?, 'committed')",
                    (page_id, path, expected),
                )
                db.execute(
                    "DELETE FROM artifact_sources WHERE artifact_id = ?",
                    (page_id,),
                )
                errors = _safe_insert_artifact_sources(db, page_id, ids)

                # Success (or partial-success) → enqueue DELETE
                pending_deletions.append(page_id)

                if errors:
                    # Round 2 P0 加固 (场景 2): log 写入失败不阻断 DELETE
                    try:
                        recovery_log.parent.mkdir(parents=True, exist_ok=True)
                        with recovery_log.open("a", encoding="utf-8") as f:
                            f.write(
                                f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"page_id={page_id} skipped={errors}\n"
                            )
                    except OSError as log_err:
                        log.warning(
                            "recover_pending: failed to write "
                            "recovery_errors.log for %s: %s",
                            page_id, log_err,
                        )
                        # Don't propagate — pending_deletions already
                        # contains page_id, so the DELETE below still runs.
            except sqlite3.IntegrityError:
                log.exception(
                    "recover_pending IntegrityError for %s", page_id,
                )
                continue  # don't enqueue DELETE
            except (OSError, ValueError) as e:
                log.warning(
                    "recover_pending error for %s: %s", page_id, e,
                )
                continue  # don't enqueue DELETE

        # Stage 2 of recovery: DELETE only successful page_ids.
        # The DELETE is outside the per-row try/except so a single
        # failing row can't poison the others.
        if pending_deletions:
            placeholders = ",".join("?" * len(pending_deletions))
            db.execute(
                f"DELETE FROM pending_wiki_commits "
                f"WHERE wiki_page_id IN ({placeholders})",
                pending_deletions,
            )
        db.commit()

    @staticmethod
    def _recover_book_releases(db: sqlite3.Connection, root: Path) -> None:
        """Complete only lineage runs whose published pointer is verifiable."""
        book_root = root / "book-wiki"
        pointer = book_root / "CURRENT.json"
        try:
            current = json.loads(pointer.read_text(encoding="utf-8"))
            run_id = current["version"]
            if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
                return
            manifest_path = book_root / ".releases" / run_id / "manifest.json"
            manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            if current.get("manifest_sha256") != manifest_hash:
                return
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("run_id") != run_id or manifest.get("release_status") != "complete":
                return
            files = manifest.get("files", {})
            if not isinstance(files, dict):
                return
            release_root = manifest_path.parent
            if any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or Path(name).is_absolute()
                or ".." in Path(name).parts
                or not _hash_matches(release_root / name, digest)
                for name, digest in files.items()
            ):
                return
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return
        row = db.execute(
            "SELECT expected_source_ids FROM build_runs WHERE run_id = ? AND status = 'running'",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        source_ids = tuple(item for item in str(row[0]).split("\n") if item)
        rel_manifest = manifest_path.relative_to(root).as_posix()
        db.execute(
            "INSERT OR REPLACE INTO artifacts(artifact_kind, artifact_id, path, content_hash, status) VALUES ('book', ?, ?, ?, 'published')",
            (run_id, rel_manifest, manifest_hash),
        )
        db.execute("DELETE FROM artifact_sources WHERE artifact_id = ?", (run_id,))
        # Plan: 2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
        # Book recovery uses the same helper — orphans are written to
        # the same recovery_errors.log so ops sees the skip uniformly.
        book_errors = _safe_insert_artifact_sources(db, run_id, source_ids)
        if book_errors:
            recovery_log = root / ".index" / "lineage" / "recovery_errors.log"
            try:
                recovery_log.parent.mkdir(parents=True, exist_ok=True)
                with recovery_log.open("a", encoding="utf-8") as f:
                    f.write(
                        f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"run_id={run_id} skipped={book_errors}\n"
                    )
            except OSError as log_err:
                log.warning(
                    "recover_book_releases: failed to write "
                    "recovery_errors.log for %s: %s", run_id, log_err,
                )
        db.execute(
            "UPDATE build_runs SET status = 'published', artifact_id = ? WHERE run_id = ?",
            (run_id, run_id),
        )
        db.execute(
            "UPDATE build_members SET status = 'published' WHERE run_id = ? AND status IN ('planned', 'running', 'staged')",
            (run_id,),
        )
        db.execute(
            "UPDATE sources SET status = 'book_compiled' "
            "WHERE source_id IN (SELECT source_id FROM artifact_sources WHERE artifact_id = ?) "
            "AND status = 'book_pending'",
            (run_id,),
        )
        db.commit()

    def prepare_wiki_commits(self, entries) -> None:
        with self._db:
            for page_id, source_ids, path, digest in entries:
                old = self._db.execute(
                    "SELECT path, content_hash FROM pending_wiki_commits WHERE wiki_page_id = ?",
                    (page_id,),
                ).fetchone()
                if old and old[1] != digest:
                    # A previous process may have flushed the file and then
                    # crashed before recovery cleared its pending row.  If the
                    # on-disk bytes still match that row, the commit completed;
                    # replace the stale intent.  Otherwise retain the conflict
                    # guard against two different writers.
                    target = self._project_root / str(old[0])
                    completed = target.is_file() and _hash_matches(target, old[1])
                    if not completed:
                        raise ValueError(f"pending Wiki commit conflict: {page_id}")
                    self._db.execute("DELETE FROM pending_wiki_commits WHERE wiki_page_id = ?", (page_id,))
                self._db.execute("INSERT OR REPLACE INTO pending_wiki_commits VALUES (?, ?, ?, ?)", (page_id, "\n".join(source_ids), path, digest))

    def pending_wiki_commits(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self._db.execute("SELECT wiki_page_id FROM pending_wiki_commits ORDER BY wiki_page_id"))

    def clear_pending_wiki_commit(self, page_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM pending_wiki_commits WHERE wiki_page_id = ?", (page_id,))

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

    def ensure_source(self, source_path: str | Path, *,
                      source_text: str | None = None) -> str | None:
        """Register the actual ingestion input without resetting unchanged state."""
        from ..utils.path import canonical_raw_key

        raw = str(source_path)
        is_url = raw.startswith(("https://", "http://"))
        external = False
        if is_url:
            key = raw
        else:
            try:
                key = canonical_raw_key(raw, self._project_root)
            except ValueError:
                if not Path(raw).is_absolute():
                    raise
                # In-memory/API ingestion may receive a source file outside the
                # project. Keep a stable absolute identity, but never read that
                # file implicitly; callers must provide source_text.
                key = Path(raw).resolve(strict=False).as_posix()
                external = True
        existing = self.source_id_for_path(key)
        path = self._project_root / key
        if not is_url and not external and path.is_file():
            content = path.read_bytes()
        elif source_text is not None:
            content = source_text.encode("utf-8")
        elif existing is not None:
            return existing
        elif is_url:
            content = raw.encode("utf-8")
        else:
            return None
        digest = hashlib.sha256(content).hexdigest()
        source_id = existing or "src-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        if existing is None:
            self.register_source(source_id, key, digest, "discovered")
        elif self.source(existing)["source_hash"] != digest:
            self.register_source(existing, key, digest, "stale")
        return source_id

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
                         input_snapshot: str, *, wiki_snapshot: str = "",
                         book_id: str = "", run_id: str | None = None) -> str:
        run_id = run_id or uuid.uuid4().hex
        existing = self._db.execute(
            "SELECT run_id FROM build_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if existing is not None:
            return run_id
        self._db.execute(
            """INSERT INTO build_runs(
                   run_id, expected_source_ids, input_snapshot, status,
                   wiki_snapshot, book_id, artifact_id
               ) VALUES (?, ?, ?, 'running', ?, ?, '')""",
            (run_id, "\n".join(sorted(expected_source_ids)), input_snapshot,
             wiki_snapshot, book_id),
        )
        self._db.commit()
        return run_id

    def build_run(self, run_id: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM build_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def build_runs(self, *, status: str | None = None) -> tuple[dict, ...]:
        query = "SELECT * FROM build_runs"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY run_id"
        return tuple(dict(row) for row in self._db.execute(query, params))

    def update_build_run(self, run_id: str, status: str, *, artifact_id: str = "") -> None:
        if self.build_run(run_id) is None:
            raise KeyError(run_id)
        self._db.execute(
            "UPDATE build_runs SET status = ?, artifact_id = CASE WHEN ? = '' THEN artifact_id ELSE ? END WHERE run_id = ?",
            (status, artifact_id, artifact_id, run_id),
        )
        self._db.commit()

    def fail_build_run(self, run_id: str, reason: str) -> None:
        self.update_build_run(run_id, "failed")
        self._db.execute(
            "UPDATE build_members SET status = 'failed' WHERE run_id = ? AND status NOT IN ('published', 'failed')",
            (run_id,),
        )
        self._db.execute(
            "INSERT OR IGNORE INTO source_reasons(source_id, reason) "
            "SELECT source_id, ? FROM build_members WHERE run_id = ?",
            (f"book_build:{reason}", run_id),
        )
        self._db.commit()

    def record_build_member(self, run_id: str, source_id: str,
                            chapter_id: str, status: str, *, input_hash: str = "",
                            output_hash: str = "", output_path: str = "") -> None:
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
               ON CONFLICT(run_id, source_id, chapter_id) DO UPDATE SET
                 status=excluded.status,
                 input_hash=CASE WHEN excluded.input_hash = '' THEN build_members.input_hash ELSE excluded.input_hash END,
                 output_hash=CASE WHEN excluded.output_hash = '' THEN build_members.output_hash ELSE excluded.output_hash END,
                 output_path=CASE WHEN excluded.output_path = '' THEN build_members.output_path ELSE excluded.output_path END""",
            (run_id, source_id, chapter_id, status),
        )
        self._db.execute(
            "UPDATE build_members SET input_hash = CASE WHEN ? = '' THEN input_hash ELSE ? END, "
            "output_hash = CASE WHEN ? = '' THEN output_hash ELSE ? END, "
            "output_path = CASE WHEN ? = '' THEN output_path ELSE ? END "
            "WHERE run_id = ? AND source_id = ? AND chapter_id = ?",
            (input_hash, input_hash, output_hash, output_hash,
             output_path, output_path, run_id, source_id, chapter_id),
        )
        self._db.commit()

    def build_members(self, run_id: str) -> tuple[tuple[str, str, str], ...]:
        rows = self._db.execute(
            "SELECT source_id, chapter_id, status FROM build_members WHERE run_id = ? ORDER BY source_id, chapter_id",
            (run_id,),
        )
        return tuple(tuple(row) for row in rows)

    def build_member_details(self, run_id: str) -> tuple[dict, ...]:
        return tuple(dict(row) for row in self._db.execute(
            "SELECT * FROM build_members WHERE run_id = ? ORDER BY source_id, chapter_id",
            (run_id,),
        ))

    def record_book_release(self, run_id: str, source_ids: tuple[str, ...],
                            path: str, content_hash: str) -> None:
        """Atomically mark the verified release and its build members published."""
        if self.build_run(run_id) is None:
            raise KeyError(run_id)
        for source_id in source_ids:
            if self._db.execute(
                "SELECT 1 FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone() is None:
                raise ValueError(f"unknown source: {source_id}")
        with self._db:
            self._db.execute(
                """INSERT INTO artifacts(artifact_kind, artifact_id, path,
                       content_hash, status) VALUES ('book', ?, ?, ?, 'published')
                   ON CONFLICT(artifact_id) DO UPDATE SET
                       artifact_kind='book', path=excluded.path,
                       content_hash=excluded.content_hash, status='published'""",
                (run_id, path, content_hash),
            )
            self._db.execute("DELETE FROM artifact_sources WHERE artifact_id = ?", (run_id,))
            # Plan: 2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
            # The caller already pre-validates every source_id, so
            # _safe_insert_artifact_sources returns [] in the happy path.
            # Plan records skipped (FK orphan) into the same
            # recovery_errors.log so ops sees the skip uniformly.
            errors = _safe_insert_artifact_sources(self._db, run_id, source_ids)
            if errors:
                log.warning(
                    "record_book_release: %s skipped source_ids=%s",
                    run_id, errors,
                )
            self._db.execute(
                "UPDATE build_members SET status = 'published' "
                "WHERE run_id = ? AND status IN ('running', 'staged')",
                (run_id,),
            )
            self._db.execute(
                "UPDATE sources SET status = 'book_compiled' "
                "WHERE source_id IN (SELECT source_id FROM artifact_sources WHERE artifact_id = ?) "
                "AND status = 'book_pending'",
                (run_id,),
            )
            self._db.execute(
                "UPDATE build_runs SET status = 'published', artifact_id = ? WHERE run_id = ?",
                (run_id, run_id),
            )

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
            # Plan: 2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
            # Run-time write path. A FK orphan here is a real bug (Stage 5
            # produced a source_id that wasn't registered). Surface it via
            # DataConsistencyError so commit_ingest fails loudly and the
            # `with self._db:` block rolls back the artifact row too.
            errors = _safe_insert_artifact_sources(self._db, artifact_id, source_ids)
            fk_orphans = [sid for sid, kind in errors if kind == "FK violation"]
            if fk_orphans:
                from ..lib.errors import DataConsistencyError
                raise DataConsistencyError(
                    f"link_artifact({artifact_kind}/{artifact_id}): "
                    f"orphan source_ids={fk_orphans}"
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
        pending += self._db.execute("SELECT COUNT(*) FROM pending_wiki_commits").fetchone()[0]
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
