import hashlib

import pytest

from src.lineage import LineageStore
from src.lineage.api import _safe_insert_artifact_sources


def test_reopen_recovers_only_matching_files_and_is_idempotent(tmp_path):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "ingested")
    digest = hashlib.sha256(b"new content").hexdigest()
    store.prepare_wiki_commits([
        ("wiki-1", ("src-1",), "wiki/a.md", digest),
        ("wiki-2", ("src-1",), "wiki/b.md", digest),
    ])
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_bytes(b"new content")
    (tmp_path / "wiki/b.md").write_bytes(b"old content")

    reopened = LineageStore.open(tmp_path)
    assert reopened.artifact_sources("wiki-1") == ("src-1",)
    assert reopened.artifact_sources("wiki-2") == ()
    assert reopened.pending_wiki_commits() == ("wiki-2",)
    assert not reopened.health().ok
    assert LineageStore.open(tmp_path).artifacts() == reopened.artifacts()

    (tmp_path / "wiki/b.md").write_bytes(b"new content")
    recovered = LineageStore.open(tmp_path)
    assert recovered.pending_wiki_commits() == ()
    assert recovered.artifact_sources("wiki-2") == ("src-1",)
    assert recovered.health().ok


def test_pending_conflict_rejected_and_prepare_batch_is_atomic(tmp_path):
    store = LineageStore.open(tmp_path)
    store.prepare_wiki_commits([("a", (), "wiki/a.md", "old")])
    with pytest.raises(ValueError, match="pending Wiki commit"):
        store.prepare_wiki_commits([
            ("b", (), "wiki/b.md", "new"),
            ("a", (), "wiki/a.md", "different"),
        ])
    assert store.pending_wiki_commits() == ("a",)


def test_pending_wiki_commit_blocks_book_even_when_old_artifact_exists(tmp_path):
    from src.kc.views.book.materialize import materialize_book_manifest

    store = LineageStore.open(tmp_path)
    store.prepare_wiki_commits([("a", (), "wiki/a.md", "new")])
    assert "lineage:pending_wiki_commits" in materialize_book_manifest(tmp_path).blocking


# ---------------------------------------------------------------------------
# Plan: 2026-09-19-v7-stage2-i5-lineage-unblock.md Task 2
# _safe_insert_artifact_sources + _recover_pending duplicate-safe + log on failure.
# Reproduces novel-wiki-v2 line 148 crash: dirty pending_wiki_commits with
# duplicate source_ids used to hit UNIQUE constraint during INSERT, leaving the
# whole lineage state.db locked out.
# ---------------------------------------------------------------------------


@pytest.fixture
def store_with_pending(tmp_path):
    """Build a LineageStore with a single registered source, ready for
    recovery tests."""
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "ingested")
    return store


def _insert_artifact_row(db, artifact_id: str) -> None:
    """Insert an artifacts row so the artifact_sources FK target exists.
    The helper assumes this has been done by the caller (as _recover_pending
    does via INSERT OR REPLACE INTO artifacts).
    """
    db.execute(
        "INSERT OR REPLACE INTO artifacts"
        "(artifact_kind, artifact_id, path, content_hash, status) "
        "VALUES ('wiki', ?, 'wiki/x.md', 'hash', 'committed')",
        (artifact_id,),
    )
    db.commit()


def test_helper_dedupes_duplicate_source_ids(tmp_path):
    """When the same source_id is given twice, helper stores one row, returns
    no errors. (Used to crash the recovery at UNIQUE constraint.)"""
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "ingested")
    _insert_artifact_row(store._db, "wiki-x")
    errors = _safe_insert_artifact_sources(
        store._db, "wiki-x", ["src-1", "src-1", "src-1"],
    )
    assert errors == []
    assert store.artifact_sources("wiki-x") == ("src-1",)


def test_helper_silently_skips_row_already_linked(tmp_path):
    """Cross-call case: the (artifact_id, source_id) pair already exists in
    the table (e.g. concurrent writer won the race, or the caller didn't
    DELETE first). ``INSERT OR IGNORE`` swallows the UNIQUE conflict, so
    the helper raises nothing and returns no errors — the row is simply
    left as-is. This documents the contract W1 flagged: UNIQUE never
    surfaces as an error, by design.

    Spec: plan 2026-09-19-v7-stage2-i5-lineage-unblock §Task 2
    ("UNIQUE violation 不抛").
    """
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "ingested")
    _insert_artifact_row(store._db, "wiki-x")
    # Pre-link the pair, then call the helper again without deleting.
    store._db.execute(
        "INSERT INTO artifact_sources(artifact_id, source_id) VALUES (?, ?)",
        ("wiki-x", "src-1"),
    )
    store._db.commit()

    errors = _safe_insert_artifact_sources(store._db, "wiki-x", ["src-1"])

    assert errors == []  # UNIQUE is swallowed, not reported
    assert store.artifact_sources("wiki-x") == ("src-1",)  # still one row


def test_helper_swallows_fk_violation_for_orphan_source_id(tmp_path):
    """FK violation (orphan source_id not in `sources`) → log warning, add to
    errors, do NOT raise. The artifact row simply has no source link for
    the orphan."""
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "hash", "ingested")
    _insert_artifact_row(store._db, "wiki-x")
    errors = _safe_insert_artifact_sources(
        store._db, "wiki-x", ["src-1", "src-orphan", "src-1"],
    )
    assert len(errors) == 1
    assert errors[0][0] == "src-orphan"
    assert "FK violation" in errors[0][1]
    assert store.artifact_sources("wiki-x") == ("src-1",)


def test_recover_pending_handles_duplicate_source_ids_without_crashing(tmp_path, store_with_pending):
    """Dirty data: pending row has duplicate source_id. Recovery must succeed
    (no UNIQUE crash). This is the regression test for the novel-wiki-v2
    kb-20260918145517 crash observed on 2026-09-19."""
    digest = hashlib.sha256(b"content").hexdigest()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_bytes(b"content")
    # Use the same source_id twice (mimics dirty data).
    store_with_pending._db.execute(
        "INSERT INTO pending_wiki_commits VALUES (?, ?, ?, ?)",
        ("wiki-1", "src-1\nsrc-1", "wiki/a.md", digest),
    )
    store_with_pending._db.commit()

    LineageStore.open(tmp_path)  # should not raise

    reopened = LineageStore.open(tmp_path)
    assert reopened.artifact_sources("wiki-1") == ("src-1",)
    assert reopened.pending_wiki_commits() == ()


def test_recover_pending_preserves_pending_when_target_file_missing(tmp_path, store_with_pending):
    """If the on-disk file is gone (or hash mismatched), the pending row must
    stay so an operator can investigate. (Don't silently lose intent.)"""
    store_with_pending._db.execute(
        "INSERT INTO pending_wiki_commits VALUES (?, ?, ?, ?)",
        ("wiki-x", "src-1", "wiki/missing.md", "deadbeef"),
    )
    store_with_pending._db.commit()

    LineageStore.open(tmp_path)

    # Pending row must remain (operator investigation needed).
    assert store_with_pending.pending_wiki_commits() == ("wiki-x",)


def test_recover_pending_writes_recovery_errors_log_for_fk_violation(tmp_path):
    """When INSERT succeeds but contains FK violations, recovery_errors.log
    must record the skipped orphans so ops can audit."""
    digest = hashlib.sha256(b"content").hexdigest()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_bytes(b"content")
    # One valid + one orphan source_id.
    store = LineageStore.open(tmp_path)
    store._db.execute(
        "INSERT INTO pending_wiki_commits VALUES (?, ?, ?, ?)",
        ("wiki-1", "src-real\nsrc-orphan", "wiki/a.md", digest),
    )
    store._db.commit()

    LineageStore.open(tmp_path)

    log = tmp_path / ".index" / "lineage" / "recovery_errors.log"
    assert log.exists(), "recovery_errors.log must be written for FK orphans"
    content = log.read_text(encoding="utf-8")
    assert "wiki-1" in content
    assert "src-orphan" in content
    assert "FK violation" in content


def test_recover_pending_log_write_failure_does_not_block_delete(tmp_path):
    """If recovery_errors.log can't be written (disk full / readonly dir),
    the page_id is still in pending_deletions — the original commit
    shouldn't be blocked by a log failure. (Round 2 P0加固 场景 2.)"""
    digest = hashlib.sha256(b"content").hexdigest()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/a.md").write_bytes(b"content")
    store = LineageStore.open(tmp_path)
    store._db.execute(
        "INSERT INTO pending_wiki_commits VALUES (?, ?, ?, ?)",
        ("wiki-1", "src-real\nsrc-orphan", "wiki/a.md", digest),
    )
    store._db.commit()
    # Pre-create recovery_errors.log as a directory — open("a") will fail.
    log_path = tmp_path / ".index" / "lineage" / "recovery_errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.mkdir()  # directory, not file → open("a") raises IsADirectoryError

    # Should not raise even though log write fails.
    LineageStore.open(tmp_path)

    reopened = LineageStore.open(tmp_path)
    assert reopened.pending_wiki_commits() == ()  # pending cleared despite log failure
