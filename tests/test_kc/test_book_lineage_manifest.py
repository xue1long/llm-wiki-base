import json
from pathlib import Path

from src.kc.integrity.orchestrator import IntegrityGate
from src.kc.views.book import Book, Chapter, SimpleKnowledgeCoreView, rebuild_book
from src.kc.views.book.materialize import materialize_book_manifest
from src.lineage import LineageStore


def _book_fixture():
    book = Book(id="book-1", title="Book", template_id="default_v1", chapter_ids=["ch-1"])
    chapter = Chapter(
        id="ch-1", book_id="book-1", stable_key="s-1", title="Chapter 1", order=1,
        source_knowledge_unit_ids=[], wiki_page_ids=["wiki-1"], source_ids=["src-1"],
    )
    return book, (chapter,), SimpleKnowledgeCoreView(publication_version=1)


def test_materialize_manifest_freezes_source_and_wiki_page_ids(tmp_path: Path) -> None:
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "a" * 64, "wiki_committed")
    store.record_wiki_commit("wiki-1", ("src-1",), "wiki/sources/a.md", "b" * 64)

    manifest = materialize_book_manifest(tmp_path)

    assert manifest.source_ids == ("src-1",)
    assert manifest.wiki_page_ids == ("wiki-1",)
    assert manifest.policy_version == "book-lineage-v1"


def test_rebuild_rejects_page_closure_mismatch_before_writing(tmp_path: Path) -> None:
    book, chapters, core_view = _book_fixture()
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "a" * 64, "wiki_committed")
    manifest = materialize_book_manifest(tmp_path)
    output_dir = tmp_path / "book"

    report = rebuild_book(
        book, chapters, core_view, IntegrityGate(), output_dir=output_dir, apply=True,
        build_manifest=manifest,
    )

    assert report.status == "failed"
    assert "closure:wiki_page_ids" in report.reason_codes
    assert not output_dir.exists()


def test_release_manifest_is_written_only_after_release_is_complete(tmp_path: Path) -> None:
    book, chapters, core_view = _book_fixture()
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/sources/a.md", "a" * 64, "wiki_committed")
    store.record_wiki_commit("wiki-1", ("src-1",), "wiki/sources/a.md", "b" * 64)
    manifest = materialize_book_manifest(tmp_path)
    # The fixture is intentionally complete for this test.
    manifest_path = tmp_path / "book" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"run_id": "old"}), encoding="utf-8")

    report = rebuild_book(
        book, chapters, core_view, IntegrityGate(), output_dir=manifest_path.parent,
        apply=True, build_manifest=manifest,
    )

    assert report.status == "committed"
    active = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert active["run_id"] != "old"
    assert (manifest_path.parent / ".releases" / active["run_id"] / "manifest.json").exists()
