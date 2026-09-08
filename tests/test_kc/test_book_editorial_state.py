import copy
import json

from src.kc.views.book.wiki.editorial_state import (
    BookEditorialState,
    build_editorial_state,
    load_editorial_state,
    save_editorial_state,
    validate_editorial_state,
)
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


def _snapshot(tmp_path):
    pages = tuple(
        PageRecord(
            page_id,
            title,
            "concept",
            f"concepts/{page_id}.md",
            "novel-wiki",
            title,
            (ContentBlock(f"{page_id}:0", page_id, None, title, 0),),
            (),
            f"hash-{page_id}",
            len(title),
            None,
            sources=(f"raw/{page_id}.md",),
        )
        for page_id, title in (("p1", "One"), ("p2", "Two"))
    )
    return WikiSnapshot("snapshot-1", str(tmp_path / "wiki"), "v2.0", pages, ())


def _outline():
    return {
        "schema_version": "book-outline-v1",
        "book_id": "novel-wiki-book",
        "editorial_revision": 1,
        "volumes": [{
            "volume_id": "volume-001",
            "title": "Volume",
            "chapters": [{
                "chapter_id": "chapter-001",
                "title": "Chapter",
                "page_ids": ["p1", "p2"],
                "sections": [],
            }],
        }],
    }


def test_build_save_load_roundtrip_uses_four_persistent_files(tmp_path):
    state = build_editorial_state(_snapshot(tmp_path), book_id="novel-wiki-book", outline=_outline())
    save_editorial_state(tmp_path / "book-wiki", state)

    expected = (
        "book.json",
        "editorial/curation.json",
        "editorial/outline.json",
        "editorial/paths.json",
    )
    assert all((tmp_path / "book-wiki" / path).is_file() for path in expected)
    assert load_editorial_state(tmp_path / "book-wiki") == state
    assert json.loads((tmp_path / "book-wiki" / "book.json").read_text(encoding="utf-8"))["body_policy"] == "generated_only"


def test_validation_rejects_unknown_page_and_duplicate_primary_owner(tmp_path):
    state = build_editorial_state(_snapshot(tmp_path), book_id="novel-wiki-book", outline=_outline())
    pages = list(state.curation["pages"])
    pages.append({
        "page_id": "unknown",
        "disposition": "include",
        "primary_chapter_id": "chapter-001",
        "secondary_references": [],
        "reason": "bad",
        "content_hash_at_review": "hash-unknown",
    })
    pages.append({
        "page_id": "p1",
        "disposition": "include",
        "primary_chapter_id": "chapter-001",
        "secondary_references": [],
        "reason": "duplicate",
        "content_hash_at_review": "hash-p1",
    })
    broken = state.with_curation_pages(tuple(pages))
    errors = validate_editorial_state(broken, page_ids={"p1", "p2"})
    assert "unknown-page:unknown" in errors
    assert "duplicate-disposition:p1" in errors


def test_build_is_deterministic_and_preserves_page_hashes(tmp_path):
    snapshot = _snapshot(tmp_path)
    first = build_editorial_state(snapshot, book_id="novel-wiki-book", outline=_outline())
    second = build_editorial_state(snapshot, book_id="novel-wiki-book", outline=_outline())

    assert first == second
    assert [row["page_id"] for row in first.curation["pages"]] == ["p1", "p2"]
    assert [row["content_hash_at_review"] for row in first.curation["pages"]] == ["hash-p1", "hash-p2"]


def test_freshness_is_snapshot_based(tmp_path):
    state = build_editorial_state(_snapshot(tmp_path), book_id="novel-wiki-book", outline=_outline())
    assert state.book["book_freshness"] == "fresh"
    stale = state.with_book_freshness("stale")
    assert stale.book["book_freshness"] == "stale"
    assert validate_editorial_state(stale, page_ids={"p1", "p2"}) == ()


def test_validation_rejects_duplicate_chapters_and_path_body(tmp_path):
    state = build_editorial_state(_snapshot(tmp_path), book_id="novel-wiki-book", outline=_outline())
    bad_outline = copy.deepcopy(state.outline)
    bad_outline["volumes"][0]["chapters"].append(
        copy.deepcopy(bad_outline["volumes"][0]["chapters"][0])
    )
    bad_paths = copy.deepcopy(state.paths)
    bad_paths["paths"] = [{"path_id": "path-1", "body": "must not exist"}]
    broken = BookEditorialState(state.book, state.curation, bad_outline, bad_paths)
    errors = validate_editorial_state(broken)
    assert "duplicate-chapter:chapter-001" in errors
    assert "path-body-forbidden:path-1" in errors
