from __future__ import annotations

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
