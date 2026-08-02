"""Tests for src/wiki/features/dedup.py — 3-way duplicate detection."""
import pytest
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.dedup import (
    find_duplicates, find_near_duplicates,
    _title_similarity, _cosine_similarity,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.utils.slugify import slugify


# -----------------------------------------------------------------------
# _title_similarity
# -----------------------------------------------------------------------

def test_title_similarity_exact():
    assert _title_similarity("Hello", "Hello") == 1.0

def test_title_similarity_case_insensitive():
    assert _title_similarity("Hello World", "hello world") == 1.0

def test_title_similarity_different():
    assert _title_similarity("Apple", "Banana") < 0.5

def test_title_similarity_empty():
    assert _title_similarity("", "foo") == 0.0
    assert _title_similarity("foo", "") == 0.0


# -----------------------------------------------------------------------
# _cosine_similarity
# -----------------------------------------------------------------------

def test_cosine_identical():
    v = [0.5, 0.5, 0.5, 0.5]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)

def test_cosine_orthogonal():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

def test_cosine_empty():
    assert _cosine_similarity([], [1.0]) == 0.0

def test_cosine_different_lengths():
    assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0


# -----------------------------------------------------------------------
# find_duplicates — slug match (Pass 1)
# -----------------------------------------------------------------------

def test_find_duplicates_empty(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    assert find_duplicates(p) == []


def test_find_duplicates_single_entity(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body="apple"))
    assert find_duplicates(p) == []


def test_find_duplicates_slug_match(tmp_path):
    """Two entities whose titles slugify to the same value → detected."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Both slugify to "hello-world"
    write_page(p, WikiPage(id="a", title="Hello World", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="Hello-World", type=PageType.ENTITY, body="y"))
    pairs = find_duplicates(p)
    assert len(pairs) == 1
    assert pairs[0] == ("a", "b") or pairs[0] == ("b", "a")


def test_find_duplicates_cjk_slug_match(tmp_path):
    """Two entities with same CJK title slugify identically."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="e1", title="网络文学", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="e2", title="网络文学", type=PageType.ENTITY, body="y"))
    pairs = find_duplicates(p)
    assert len(pairs) == 1


def test_find_duplicates_slug_no_match(tmp_path):
    """Different titles with different slugs → not detected."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="Apple Pie", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="Banana Bread", type=PageType.ENTITY, body="y"))
    assert find_duplicates(p) == []


# -----------------------------------------------------------------------
# find_duplicates — title similarity (Pass 2)
# -----------------------------------------------------------------------

def test_find_duplicates_title_similarity_high(tmp_path):
    """Titles with >= 85% similarity → detected."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="Machine Learning Basics", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="Machine Learning Basic", type=PageType.ENTITY, body="y"))
    pairs = find_duplicates(p)
    assert len(pairs) == 1


def test_find_duplicates_title_similarity_low(tmp_path):
    """Titles with < 85% similarity → not detected."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="Machine Learning", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="Deep Reinforcement", type=PageType.ENTITY, body="y"))
    assert find_duplicates(p) == []


def test_find_duplicates_deduplicates_pairs(tmp_path):
    """Same pair not reported twice (slug match + title similarity)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # These match on BOTH slug and title similarity → only one entry
    write_page(p, WikiPage(id="a", title="Hello World", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="Hello-World", type=PageType.ENTITY, body="y"))
    pairs = find_duplicates(p)
    assert len(pairs) == 1


# -----------------------------------------------------------------------
# find_near_duplicates — vector similarity (Pass 3)
# -----------------------------------------------------------------------

def test_find_near_duplicates_no_vector_store(tmp_path):
    """Without an initialized vector store, returns [] gracefully."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))
    write_page(p, WikiPage(id="b", title="B", type=PageType.ENTITY, body="y"))
    assert find_near_duplicates(p) == []


def test_find_near_duplicates_empty_entities(tmp_path):
    """No entity pages → []."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    assert find_near_duplicates(p) == []


def test_find_near_duplicates_single_entity(tmp_path):
    """One entity → [] (need at least 2 to compare)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))
    assert find_near_duplicates(p) == []
