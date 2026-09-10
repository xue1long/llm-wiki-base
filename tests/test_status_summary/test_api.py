from __future__ import annotations

import sqlite3
from pathlib import Path

from src.status_summary import summarize_project


def _make_db(
    root: Path,
    *,
    sources=(),
    artifacts=(),
    artifact_sources=(),
    pending_wiki_commits=(),
    build_runs=(),
    build_members=(),
) -> None:
    db_path = root / ".index" / "lineage" / "state.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE sources (
                source_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE source_reasons (
                source_id TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE artifacts (
                artifact_kind TEXT NOT NULL,
                artifact_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE artifact_sources (
                artifact_id TEXT NOT NULL,
                source_id TEXT NOT NULL
            );
            CREATE TABLE pending_wiki_commits (
                wiki_page_id TEXT PRIMARY KEY,
                source_ids TEXT NOT NULL,
                path TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE TABLE build_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL
            );
            CREATE TABLE build_members (
                run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                status TEXT NOT NULL,
                input_hash TEXT NOT NULL DEFAULT '',
                output_hash TEXT NOT NULL DEFAULT '',
                output_path TEXT NOT NULL DEFAULT ''
            );
            """
        )
        db.executemany(
            "INSERT INTO sources VALUES (?, ?, ?, ?)",
            [(source_id, path, "hash", status) for source_id, path, status in sources],
        )
        db.executemany(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
            [
                (kind, artifact_id, f"{artifact_id}.json", "hash", status)
                for kind, artifact_id, status in artifacts
            ],
        )
        db.executemany(
            "INSERT INTO artifact_sources VALUES (?, ?)", artifact_sources
        )
        db.executemany(
            "INSERT INTO pending_wiki_commits VALUES (?, ?, ?, ?)",
            [
                (page_id, source_ids, f"{page_id}.md", "hash")
                for page_id, source_ids in pending_wiki_commits
            ],
        )
        db.executemany("INSERT INTO build_runs VALUES (?, ?)", build_runs)
        db.executemany(
            "INSERT INTO build_members(run_id, source_id, chapter_id, status) "
            "VALUES (?, ?, ?, ?)",
            build_members,
        )


def test_summary_combines_raw_kc_wiki_and_book_state(tmp_path: Path) -> None:
    _make_db(
        tmp_path,
        sources=[("source-1", "raw/a.md", "ingested")],
        artifacts=[
            ("kc", "kc-1", "committed"),
            ("wiki", "wiki-1", "committed"),
            ("book", "book-1", "published"),
        ],
        artifact_sources=[("kc-1", "source-1"), ("wiki-1", "source-1"), ("book-1", "source-1")],
        build_runs=[("run-1", "published")],
        build_members=[("run-1", "source-1", "chapter-1", "published")],
    )

    summary = summarize_project(tmp_path)

    assert summary.status == "book_compiled"
    source = summary.sources[0]
    assert source.raw_status == "ingested"
    assert source.kc_status == "committed"
    assert source.wiki_status == "committed"
    assert source.book_status == "published"
    assert source.overall_status == "book_compiled"


def test_summary_marks_pending_wiki_commit_as_in_progress(tmp_path: Path) -> None:
    _make_db(
        tmp_path,
        sources=[("source-1", "raw/a.md", "ingested")],
        pending_wiki_commits=[("wiki-1", "source-1")],
    )

    summary = summarize_project(tmp_path)

    assert summary.status == "in_progress"
    assert summary.sources[0].wiki_status == "pending"
    assert summary.sources[0].overall_status == "in_progress"


def test_summary_serializes_without_exposing_database_objects(tmp_path: Path) -> None:
    _make_db(tmp_path, sources=[("source-1", "raw/a.md", "ingested")])

    payload = summarize_project(tmp_path).to_dict()

    assert payload["status"] == "ingested"
    assert payload["database_path"] == str(
        tmp_path / ".index" / "lineage" / "state.db"
    )
    assert payload["sources"][0]["source_id"] == "source-1"


def test_summary_surfaces_failure_and_missing_database(tmp_path: Path) -> None:
    _make_db(
        tmp_path,
        sources=[("source-1", "raw/a.md", "failed")],
    )
    failed = summarize_project(tmp_path)
    assert failed.status == "failed"
    assert failed.sources[0].overall_status == "failed"

    missing = summarize_project(tmp_path / "missing")
    assert missing.status == "unavailable"
    assert missing.sources == ()
