from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import build_series_assignment


def page(page_id, taxonomy="book-a", *, source=True, digest=None, relation_targets=()):
    return PageRecord(
        page_id, page_id, "concept", f"concepts/{page_id}.md", taxonomy, "summary",
        (ContentBlock(f"{page_id}:0", page_id, None, "body", 0),), relation_targets,
        digest or f"hash-{page_id}", 4, None, sources=(f"source-{page_id}",) if source else (),
    )


def snapshot(*pages):
    return WikiSnapshot("snap-1", "wiki", "v1", tuple(pages), ())


def test_empty_snapshot_has_stable_shape_and_metrics():
    result = build_series_assignment(snapshot(), candidate_taxonomies=("book-a",))
    assert result["assignments"] == []
    assert {key: result["metrics"][key] for key in ("total_pages", "assigned_pages", "ledger_pages")} == {
        "total_pages": 0, "assigned_pages": 0, "ledger_pages": 0,
    }
    assert len(result["fingerprint"]) == 64


def test_unique_primary_is_assigned_and_secondary_topics_are_references():
    result = build_series_assignment(snapshot(page("p1", "book-a")), candidate_taxonomies=("book-a",))
    row = result["assignments"][0]
    assert row["primary_book_id"] == "book-a"
    assert row["chapter_id"] == "chapter-book-a-concept"
    assert row["secondary_topics"] == []
    assert row["ledger_reason"] is None


def test_unknown_taxonomy_and_missing_source_are_ledgered():
    result = build_series_assignment(
        snapshot(page("p1", "unknown"), page("p2", "book-a", source=False)),
        candidate_taxonomies=("book-a",),
    )
    reasons = {row["page_id"]: row["ledger_reason"] for row in result["assignments"]}
    assert reasons == {"p1": "unknown_taxonomy", "p2": "missing_source"}
    assert result["metrics"]["assigned_pages"] == 0


def test_duplicate_canonical_hash_is_ledgered_and_does_not_enter_body():
    result = build_series_assignment(
        snapshot(page("p1", digest="same"), page("p2", digest="same")),
        candidate_taxonomies=("book-a",),
    )
    rows = {row["page_id"]: row for row in result["assignments"]}
    assert rows["p1"]["primary_book_id"] == "book-a"
    assert rows["p2"]["ledger_reason"] == "duplicate_canonical"
    assert result["metrics"]["duplicate_pages"] == 1


def test_duplicate_page_id_and_cross_book_relation_are_fail_closed():
    result = build_series_assignment(
        snapshot(page("p1", "book-a", relation_targets=(("supports", "p2"),)), page("p1", "book-b")),
        candidate_taxonomies=("book-a", "book-b"),
    )
    assert all(row["primary_book_id"] is None for row in result["assignments"])
    assert {row["ledger_reason"] for row in result["assignments"]} == {"duplicate_page_id"}
    assert result["metrics"]["conflict_pages"] == 1


def test_fingerprint_and_order_are_replayable():
    first = build_series_assignment(snapshot(page("z"), page("a")), candidate_taxonomies=("book-a",))
    second = build_series_assignment(snapshot(page("a"), page("z")), candidate_taxonomies=("book-a",))
    assert first == second
