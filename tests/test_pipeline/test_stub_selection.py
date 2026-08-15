"""Tests for stub candidate selection (_rank_stub_candidates).

batch-50 regression: 16 document-title stub entities (e.g.
`必备资料-15-顺眼谈文章的画面感-43c5df10` — a hyphenated variant of the source
page id) inflated the index with near-empty pages, and stub suppression was
all-or-nothing (over the cap → zero stubs).
"""
from src.pipeline.ingest import _rank_stub_candidates


def _src_hash(slug: str) -> str:
    return slug.rsplit("-", 1)[-1]


def test_document_title_variant_excluded():
    """A stub that is a hyphen-variant of the source page (same trailing hash)
    is dropped — the source page already represents the document."""
    source_slug = "必备资料15顺眼谈文章的画面感-43c5df10"
    missing = {
        "必备资料-15-顺眼谈文章的画面感-43c5df10",  # doc-title variant
        "真实概念",                                   # legit stub
    }
    result = _rank_stub_candidates(missing, 10, source_slug, {}, set())
    assert "真实概念" in result
    assert "必备资料-15-顺眼谈文章的画面感-43c5df10" not in result


def test_different_hash_kept():
    """A slug sharing text with the source but a DIFFERENT hash is a real entity."""
    source_slug = "大纲示例免费女频大纲-9aa69399"
    missing = {"大纲示例免费女频大纲-00000000"}  # different hash → real reference
    result = _rank_stub_candidates(missing, 10, source_slug, {}, set())
    assert missing == set(result)


def test_ranking_keeps_most_referenced_when_over_cap():
    """Over the cap, keep the most-referenced slugs."""
    missing = {f"concept-{i}" for i in range(5)}
    refs = {f"concept-{i}": (5 - i) for i in range(5)}  # concept-0 most referenced
    result = _rank_stub_candidates(missing, 3, "source-abc12345", refs, set())
    assert len(result) == 3
    assert "concept-0" in result and "concept-1" in result and "concept-2" in result
    assert "concept-4" not in result


def test_analyzer_named_preferred():
    """Over the cap, analyzer-named slugs outrank unnamed ones."""
    missing = {"a", "b", "c"}
    refs = {"a": 1, "b": 1, "c": 1}
    analyzer = {"a", "b"}
    result = _rank_stub_candidates(missing, 2, "src-12345678", refs, analyzer)
    assert set(result) == {"a", "b"}


def test_under_cap_all_kept():
    missing = {"x", "y"}
    result = _rank_stub_candidates(missing, 10, "src-12345678", {"x": 1, "y": 1}, set())
    assert set(result) == missing
