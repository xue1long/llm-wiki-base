# tests/test_wiki/test_review.py
from src.wiki.features.review import load_reviews, add_review, resolve_review
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def test_add_review_creates_item(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    item = add_review(p, "missing-page", "Foo missing",
                     detail="...", confidence=0.9, search_queries=["foo"])
    assert item.type == "missing-page"
    assert item.status == "open"
    assert item.normalized_title == "foo missing"
    assert len(item.id) > 0

    items = load_reviews(p)
    assert len(items) == 1


def test_add_review_dedupes(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    a = add_review(p, "missing-page", "Foo missing", confidence=0.9, detail="")
    b = add_review(p, "missing-page", "FOO  MISSING", confidence=0.8, detail="")
    assert a.id == b.id  # same item
    assert len(load_reviews(p)) == 1


def test_resolve_review_moves_item(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    item = add_review(p, "duplicate-page", "Dup", confidence=0.5, detail="")
    resolve_review(p, item.id, action="merged")

    open_items = load_reviews(p)
    resolved_items = load_reviews(p, resolved=True)
    assert len(open_items) == 0
    assert len(resolved_items) == 1
    assert resolved_items[0].status == "merged"