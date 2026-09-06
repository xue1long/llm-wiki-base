from collections import Counter

from src.kc.views.book.wiki.aggregator import aggregate_chapter, order_pages_within_chapter, relation_stats
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


def page(pid, kind="concept", grade="B", blocks=()):
    return PageRecord(pid, pid.title(), kind, f"wiki/concepts/{pid}.md", "topic", "summary", tuple(blocks), (), "hash", 10, None, "")


def test_aggregate_preserves_blocks_and_unknown_heading_bucket():
    pages = {"p1": page("p1", blocks=(
        ContentBlock("p1:0", "p1", None, "preamble", 0),
        ContentBlock("p1:1", "p1", "Unusual heading", "body", 1),
    ))}
    draft = aggregate_chapter({"chapter_id": "c1", "page_ids": ["p1"]}, pages)
    assert draft.page_ids == ("p1",)
    assert Counter(draft.block_ids) == Counter(("p1:0", "p1:1"))
    assert draft.bucket_index["未分类"] == ("p1:1",)
    assert draft.bucket_index["前言"] == ("p1:0",)


def test_rule_order_is_stable_and_uses_page_id_tiebreak():
    pages = {k: page(k, kind="entity") for k in ("b", "a")}
    chapter = {"chapter_id": "c", "page_ids": ["b", "a"]}
    assert order_pages_within_chapter(chapter, pages, mode="rule_only") == ("a", "b")


def test_relation_stats_excludes_namespace_edges_and_counts_excluded_sources():
    p = page("p1")
    p = PageRecord(p.page_id, p.title, p.page_type, p.path, p.primary_taxonomy, p.summary,
                   p.content_blocks, (("taxonomy_of", "taxonomy-写作技法"),
                                      ("references", "source-1"),
                                      ("references", "missing")), p.content_sha256,
                   p.char_count, p.token_count, p.custom_type, p.sources)
    snapshot = WikiSnapshot("s", "/tmp/wiki", "v2.0", (p,), ("source-1",))
    stats = relation_stats(snapshot)
    assert stats["ignored_namespace"] == 1
    assert stats["total"] == 2
    assert stats["unresolved"] == 1
