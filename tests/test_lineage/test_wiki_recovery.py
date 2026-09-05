import hashlib

import pytest

from src.lineage import LineageStore


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
