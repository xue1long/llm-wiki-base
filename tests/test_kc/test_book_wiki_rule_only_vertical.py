from src.kc.views.book.wiki.compiler import compile_book
from src.kc.views.book.wiki.editorial_state import build_editorial_state
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.quality_gate import check_quality_gate


def _fixture(tmp_path, *, empty_second_chapter=False):
    pages = tuple(
        PageRecord(
            page_id,
            title,
            "concept",
            f"concepts/{page_id}.md",
            "tax",
            title,
            (ContentBlock(f"{page_id}:0", page_id, "正文", f"Body {page_id}", 0),),
            (),
            f"hash-{page_id}",
            10,
            None,
            sources=(f"raw/{page_id}.md",),
        )
        for page_id, title in (("p1", "One"), ("p2", "Two"))
    )
    snapshot = WikiSnapshot("snapshot-1", str(tmp_path / "wiki"), "v2.0", pages, ())
    chapters = [
        {"chapter_id": "chapter-001", "title": "First", "page_ids": ["p1"]},
        {"chapter_id": "chapter-002", "title": "Second", "page_ids": [] if empty_second_chapter else ["p2"]},
    ]
    outline = {
        "schema_version": "book-outline-v1",
        "book_id": "novel-wiki-book",
        "volumes": [{"volume_id": "volume-001", "chapters": chapters}],
    }
    state = build_editorial_state(snapshot, book_id="novel-wiki-book", outline=outline)
    return snapshot, pages, state


def test_rule_only_vertical_slice_emits_source_and_revision_quality_fields(tmp_path):
    snapshot, pages, state = _fixture(tmp_path)
    artifact = compile_book(
        snapshot,
        [state.outline],
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    assert artifact.validation_errors == ()
    assert artifact.manifest["chapter_body_present"] is True
    assert artifact.manifest["section_source_ids_present"] is True
    assert artifact.manifest["curation_revision_present"] is True
    assert artifact.manifest["outline_revision_present"] is True
    assert artifact.manifest["release_status"] == "complete"
    assert artifact.manifest["wiki_snapshot_hash"] == snapshot.snapshot_id
    assert artifact.manifest["release_manifest_hash"]
    assert artifact.manifest["chapter_source_ids"]["volume-001__chapter-001.md"] == ["raw/p1.md"]
    assert check_quality_gate(artifact.manifest).ok


def test_rule_only_quality_gate_blocks_empty_chapter(tmp_path):
    snapshot, pages, state = _fixture(tmp_path, empty_second_chapter=True)
    artifact = compile_book(
        snapshot,
        [state.outline],
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    report = check_quality_gate(artifact.manifest)
    assert "chapter_body_missing" in report.rule_blockers


def test_duplicate_disposition_is_not_compiled_as_book_body(tmp_path):
    snapshot, pages, state = _fixture(tmp_path)
    rows = [dict(row) for row in state.curation["pages"]]
    rows[1]["disposition"] = "duplicate"
    rows[1]["primary_chapter_id"] = None
    state = state.with_curation_pages(tuple(rows))
    outline = dict(state.outline)
    outline["volumes"] = [{
        **outline["volumes"][0],
        "chapters": [{"chapter_id": "chapter-001", "title": "First", "page_ids": ["p1"]}],
    }]
    state = type(state)(state.book, state.curation, outline, state.paths)
    artifact = compile_book(
        snapshot,
        [outline],
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    assert artifact.validation_errors == ()
    assert artifact.manifest["page_count"] == 1
    assert "Body p2" not in (artifact.version_dir / "volume-001__chapter-001.md").read_text(encoding="utf-8")


def test_stale_review_hash_fails_closed(tmp_path):
    snapshot, pages, state = _fixture(tmp_path)
    rows = [dict(row) for row in state.curation["pages"]]
    rows[0]["content_hash_at_review"] = "stale"
    state = state.with_curation_pages(tuple(rows))
    artifact = compile_book(
        snapshot,
        [state.outline],
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        editorial_state=state,
    )

    assert "editorial-state:content-hash-mismatch:p1" in artifact.validation_errors
