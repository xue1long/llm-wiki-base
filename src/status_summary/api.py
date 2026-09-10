"""Derive one project status from the existing lineage database.

This module intentionally depends only on the SQLite storage contract and the
standard library.  It does not import or mutate any pipeline, Wiki, KC, Book,
or queue module, so it can be removed or reused independently.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


_FAILURE_STATUSES = {"failed", "permanent_failed"}
_BLOCKED_STATUSES = {"blocked", "raw_unsupported"}
_IN_PROGRESS_STATUSES = {
    "pending", "running", "staged", "in_progress", "book_pending",
}


@dataclass(frozen=True)
class SourceStatus:
    """One source's status across all persisted lifecycle stages."""

    source_id: str
    source_path: str
    raw_status: str
    kc_status: str
    wiki_status: str
    book_status: str
    overall_status: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_path": self.source_path,
            "raw_status": self.raw_status,
            "kc_status": self.kc_status,
            "wiki_status": self.wiki_status,
            "book_status": self.book_status,
            "overall_status": self.overall_status,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ProjectStatusSummary:
    """Project-level status plus the per-source breakdown."""

    project_root: Path
    database_path: Path
    status: str
    sources: tuple[SourceStatus, ...]
    pending_wiki_commits: int = 0
    build_runs: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "database_path": str(self.database_path),
            "status": self.status,
            "pending_wiki_commits": self.pending_wiki_commits,
            "build_runs": self.build_runs,
            "sources": [source.to_dict() for source in self.sources],
        }


def summarize_project(project_root: Path) -> ProjectStatusSummary:
    """Read-only aggregation of the project's persisted lifecycle state."""
    root = Path(project_root).resolve()
    database_path = root / ".index" / "lineage" / "state.db"
    if not database_path.is_file():
        return ProjectStatusSummary(root, database_path, "unavailable", ())

    try:
        with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            rows = _read_rows(db)
    except (sqlite3.Error, OSError):
        return ProjectStatusSummary(root, database_path, "unavailable", ())

    sources = _build_sources(rows)
    return ProjectStatusSummary(
        project_root=root,
        database_path=database_path,
        status=_project_status(sources),
        sources=tuple(sources),
        pending_wiki_commits=len(rows["pending_wiki_commits"]),
        build_runs=len(rows["build_runs"]),
    )


def _read_rows(db: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    tables = (
        "sources", "source_reasons", "artifacts", "artifact_sources",
        "pending_wiki_commits", "build_runs", "build_members",
    )
    result: dict[str, list[dict[str, object]]] = {}
    for table in tables:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        result[table] = [] if exists is None else [
            dict(row) for row in db.execute(f"SELECT * FROM {table}")
        ]
    return result


def _build_sources(rows: dict[str, list[dict[str, object]]]) -> list[SourceStatus]:
    linked: dict[str, dict[str, list[str]]] = {}
    for link in rows["artifact_sources"]:
        linked.setdefault(str(link["source_id"]), {}).setdefault(
            str(link["artifact_id"]), []
        )

    artifacts = {
        str(row["artifact_id"]): row for row in rows["artifacts"]
    }
    reasons: dict[str, list[str]] = {}
    for row in rows["source_reasons"]:
        reasons.setdefault(str(row["source_id"]), []).append(str(row["reason"]))

    pending_by_source: dict[str, bool] = {}
    for row in rows["pending_wiki_commits"]:
        for source_id in str(row.get("source_ids", "")).splitlines():
            if source_id:
                pending_by_source[source_id] = True

    build_by_source: dict[str, list[str]] = {}
    for row in rows["build_members"]:
        build_by_source.setdefault(str(row["source_id"]), []).append(
            str(row["status"])
        )

    result = []
    for row in rows["sources"]:
        source_id = str(row["source_id"])
        source_artifacts = [
            artifacts[artifact_id]
            for artifact_id in linked.get(source_id, {})
            if artifact_id in artifacts
        ]
        kc_status = _artifact_status(
            [row for row in source_artifacts if row["artifact_kind"] == "kc"]
        )
        wiki_status = (
            "pending" if pending_by_source.get(source_id) else _artifact_status(
                [row for row in source_artifacts if row["artifact_kind"] == "wiki"]
            )
        )
        book_status = _book_status(
            [row for row in source_artifacts if row["artifact_kind"] == "book"],
            build_by_source.get(source_id, []),
        )
        raw_status = str(row["status"])
        result.append(SourceStatus(
            source_id=source_id,
            source_path=str(row["source_path"]),
            raw_status=raw_status,
            kc_status=kc_status,
            wiki_status=wiki_status,
            book_status=book_status,
            overall_status=_source_status(raw_status, kc_status, wiki_status, book_status),
            reasons=tuple(sorted(reasons.get(source_id, []))),
        ))
    return result


def _artifact_status(artifacts: list[dict[str, object]]) -> str:
    statuses = [str(row["status"]) for row in artifacts]
    if any(status in _FAILURE_STATUSES for status in statuses):
        return "failed"
    if any(status in _BLOCKED_STATUSES for status in statuses):
        return "blocked"
    if any(status in {"committed", "published"} for status in statuses):
        return "committed"
    if any(status in _IN_PROGRESS_STATUSES for status in statuses):
        return "in_progress"
    return "not_started"


def _book_status(
    artifacts: list[dict[str, object]], member_statuses: list[str]
) -> str:
    status = _artifact_status(artifacts)
    if status != "not_started":
        return "published" if status == "committed" else status
    if any(value in _FAILURE_STATUSES for value in member_statuses):
        return "failed"
    if any(value in _BLOCKED_STATUSES for value in member_statuses):
        return "blocked"
    if any(value in {"published", "committed"} for value in member_statuses):
        return "published"
    if any(value in _IN_PROGRESS_STATUSES for value in member_statuses):
        return "in_progress"
    return "not_started"


def _source_status(raw: str, kc: str, wiki: str, book: str) -> str:
    stages = (raw, kc, wiki, book)
    if any(status in _BLOCKED_STATUSES for status in stages):
        return "blocked"
    if any(status in _FAILURE_STATUSES for status in stages):
        return "failed"
    if raw in {"stale", "deleted"}:
        return raw
    if any(status in {"pending", "in_progress"} for status in stages):
        return "in_progress"
    if book == "published" or raw == "book_compiled":
        return "book_compiled"
    if wiki == "committed" or raw == "wiki_committed":
        return "wiki_committed"
    if kc == "committed" or raw == "kc_published":
        return "kc_published"
    return raw or "unknown"


def _project_status(sources: list[SourceStatus]) -> str:
    if not sources:
        return "empty"
    statuses = {source.overall_status for source in sources}
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "in_progress" in statuses:
        return "in_progress"
    return next(iter(statuses)) if len(statuses) == 1 else "partial"
