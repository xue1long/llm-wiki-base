import json
from pathlib import Path

from src.kc.views.book.materialize import materialize_book_plan
from src.lineage import LineageStore


def test_plan_reports_new_and_removed_sources_from_active_manifest(tmp_path: Path) -> None:
    book_dir = tmp_path / "book"
    book_dir.mkdir()
    (book_dir / "manifest.json").write_text(json.dumps({
        "lineage": {"source_ids": ["src-old"], "wiki_page_ids": ["wiki-old"]}
    }), encoding="utf-8")
    store = LineageStore.open(tmp_path)
    store.register_source("src-new", "raw/sources/new.md", "a" * 64, "wiki_committed")
    store.record_wiki_commit("wiki-new", ("src-new",), "wiki/new.md", "b" * 64)

    plan = materialize_book_plan(tmp_path)

    assert plan.added_source_ids == ("src-new",)
    assert plan.removed_source_ids == ("src-old",)
    assert plan.added_wiki_page_ids == ("wiki-new",)
    assert plan.removed_wiki_page_ids == ("wiki-old",)


def test_outbox_replay_is_idempotent(tmp_path: Path) -> None:
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "discovered")
    assert store.enqueue_outbox("raw:src-1:ingested", "raw_ingested", "src-1")
    assert not store.enqueue_outbox("raw:src-1:ingested", "raw_ingested", "src-1")
    assert store.replay_outbox() == ("raw:src-1:ingested",)
    assert store.replay_outbox() == ()


def test_build_snapshot_becomes_stale_after_source_change(tmp_path: Path) -> None:
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "discovered")
    run_id = store.create_build_run(("src-1",), "src-1:" + "a" * 64)

    store.register_source("src-1", "raw/a.md", "b" * 64, "stale")

    assert store.build_snapshot_is_current(run_id) is False


def test_build_lease_is_exclusive_and_releasable(tmp_path: Path) -> None:
    store = LineageStore.open(tmp_path)
    assert store.acquire_build_lease("run-1") is True
    assert store.acquire_build_lease("run-2") is False
    store.release_build_lease("run-1")
    assert store.acquire_build_lease("run-2") is True
