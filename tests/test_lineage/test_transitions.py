from __future__ import annotations

import hashlib
import json

import pytest

from src.lineage.api import LineageStore


def test_transition_records_reason_and_tombstone(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash-a", "discovered")
    store.transition_source("src-1", "discovered", "deleted", ("explicit_delete",))
    assert store.source("src-1")["status"] == "deleted"
    assert store.source_reasons("src-1") == ("explicit_delete",)


def test_build_run_members_are_idempotent(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash-a", "book_pending")
    run_id = store.create_build_run(("src-1",), "snapshot-1")
    store.record_build_member(run_id, "src-1", "chapter-1", "compiled")
    store.record_build_member(run_id, "src-1", "chapter-1", "compiled")
    assert store.build_members(run_id) == (("src-1", "chapter-1", "compiled"),)


def test_outbox_event_key_is_idempotent(tmp_path):
    store = LineageStore.open(tmp_path)
    assert store.enqueue_outbox("event-1", "source.changed", "src-1") is True
    assert store.enqueue_outbox("event-1", "source.changed", "src-1") is False
    assert store.pending_outbox() == (("event-1", "source.changed", "src-1"),)


def test_unknown_source_cannot_become_build_member(tmp_path):
    store = LineageStore.open(tmp_path)
    run_id = store.create_build_run((), "snapshot-1")
    with pytest.raises(ValueError):
        store.record_build_member(run_id, "missing", "chapter-1", "compiled")


def test_record_wiki_commit_preserves_all_source_links(tmp_path):
    store = LineageStore.open(tmp_path)
    for source_id in ("src-1", "src-2"):
        store.register_source(source_id, f"raw/{source_id}.md", "hash", "ingested")
    store.record_wiki_commit(
        "wiki-1", ("src-1", "src-2"), "wiki/synthesis/x.md", "wiki-hash"
    )
    assert store.artifact_sources("wiki-1") == ("src-1", "src-2")


def test_record_kc_commit_preserves_bundle_source_links(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "wiki_committed")
    store.record_kc_commit("bundle-1", ("src-1",), "kc/bundle/manifest.json", "kc-hash", 3)
    assert store.artifact_sources("bundle-1") == ("src-1",)


def test_book_build_records_run_members_and_release(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "book_pending")

    run_id = store.create_build_run(
        ("src-1",),
        "src-1:" + "a" * 64,
        wiki_snapshot="wiki-snapshot-1",
        book_id="book-1",
        run_id="run-book-1",
    )
    store.record_build_member(
        run_id,
        "src-1",
        "chapter-1",
        "staged",
        input_hash="page-hash",
        output_hash="chapter-hash",
        output_path="book-wiki/.releases/run-book-1/chapter.md",
    )
    store.record_book_release(
        run_id,
        ("src-1",),
        "book-wiki/.releases/run-book-1/manifest.json",
        "manifest-hash",
    )

    run = store.build_run(run_id)
    assert run is not None
    assert run["status"] == "published"
    assert run["wiki_snapshot"] == "wiki-snapshot-1"
    assert run["book_id"] == "book-1"
    assert store.build_members(run_id) == (("src-1", "chapter-1", "published"),)
    assert store.artifacts(artifact_kind="book")[0]["status"] == "published"
    assert store.source("src-1")["status"] == "book_compiled"


def test_build_history_exposes_run_and_member_statuses(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "ingested")
    run_id = store.create_build_run(("src-1",), "src-1:" + "a" * 64)
    store.record_build_member(run_id, "src-1", "chapter-1", "staged")

    assert store.build_runs()[0]["run_id"] == run_id
    assert store.build_member_details(run_id)[0]["status"] == "staged"


def test_failed_book_build_is_not_a_published_artifact(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "ingested")
    run_id = store.create_build_run(
        ("src-1",), "src-1:" + "a" * 64, run_id="run-book-2"
    )

    store.fail_build_run(run_id, "publish_failed")

    run = store.build_run(run_id)
    assert run is not None
    assert run["status"] == "failed"
    assert store.artifacts(artifact_kind="book") == ()


def test_reopen_recovers_published_book_after_database_write_window(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "book_pending")
    run_id = store.create_build_run(
        ("src-1",), "src-1:" + "a" * 64, run_id="run-book-recovery"
    )
    store._db.close()

    release = tmp_path / "book-wiki" / ".releases" / run_id
    release.mkdir(parents=True)
    chapter = release / "chapter.md"
    chapter.write_text("chapter", encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "release_status": "complete",
        "files": {"chapter.md": hashlib.sha256(chapter.read_bytes()).hexdigest()},
    }
    manifest_path = release / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "book-wiki" / "CURRENT.json").write_text(
        json.dumps({
            "version": run_id,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )

    recovered = LineageStore.open(tmp_path)
    run = recovered.build_run(run_id)
    assert run is not None
    assert run["status"] == "published"
    assert recovered.artifacts(artifact_kind="book", status="published")
    assert recovered.source("src-1")["status"] == "book_compiled"


# ---------------------------------------------------------------------------
# Plan: 2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2 (code-review C2)
# The book-release paths were switched to _safe_insert_artifact_sources but
# had no coverage. These two tests guard both the recovery path and the
# normal release path.
# ---------------------------------------------------------------------------


def test_book_release_recovery_logs_orphan_source(tmp_path):
    """_recover_book_releases routes skipped orphans into recovery_errors.log
    instead of crashing the whole recovery (the pre-fix behaviour raised
    IntegrityError out of LineageStore.open)."""
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "book_pending")
    # The run expects an orphan source_id that was never registered.
    run_id = store.create_build_run(
        ("src-1", "src-orphan"), "snapshot", run_id="run-book-orphan",
    )
    store._db.close()

    release = tmp_path / "book-wiki" / ".releases" / run_id
    release.mkdir(parents=True)
    manifest_path = release / "manifest.json"
    manifest_path.write_text(
        json.dumps({"run_id": run_id, "release_status": "complete", "files": {}}),
        encoding="utf-8",
    )
    (tmp_path / "book-wiki" / "CURRENT.json").write_text(
        json.dumps({
            "version": run_id,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )

    recovered = LineageStore.open(tmp_path)  # must not raise

    # The valid source linked; the orphan was skipped and logged.
    assert recovered.artifact_sources(run_id) == ("src-1",)
    assert recovered.build_run(run_id)["status"] == "published"
    log = tmp_path / ".index" / "lineage" / "recovery_errors.log"
    assert log.exists(), "orphan skip must be recorded for ops"
    content = log.read_text(encoding="utf-8")
    assert run_id in content
    assert "src-orphan" in content
    assert "FK violation" in content


def test_record_book_release_links_sources_without_recovery_log(tmp_path):
    """Normal release path: every source_id is valid, so the helper returns
    no orphans and no recovery_errors.log is written. Guards against the
    helper spuriously reporting errors on the happy path."""
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "book_pending")
    store.register_source("src-2", "raw/b.md", "b" * 64, "book_pending")
    run_id = store.create_build_run(
        ("src-1", "src-2"), "src-1:" + "a" * 64, run_id="run-book-clean",
    )

    store.record_book_release(
        run_id,
        ("src-1", "src-2"),
        "book-wiki/.releases/run-book-clean/manifest.json",
        "manifest-hash",
    )

    assert store.artifact_sources(run_id) == ("src-1", "src-2")
    assert store.build_run(run_id)["status"] == "published"
    assert not (tmp_path / ".index" / "lineage" / "recovery_errors.log").exists()
