"""Tests for src.wiki.types."""
from src.wiki.core.types import (
    PageType,
    WikiPage,
    ReviewItem,
    make_review_item,
)


def test_page_type_enum():
    assert PageType.SOURCE == "source"
    assert PageType.ENTITY == "entity"
    assert PageType.CONCEPT == "concept"
    assert PageType.SYNTHESIS == "synthesis"


def test_wiki_page_round_trip_frontmatter():
    page = WikiPage(
        id="abc", title="Test", type=PageType.ENTITY,
        sources=["raw/sources/foo.pdf"],
        created_at=1000, updated_at=2000, body="Hello world",
    )
    d = page.to_frontmatter_dict()
    assert d["id"] == "abc"
    assert d["type"] == "entity"
    assert d["sources"] == ["raw/sources/foo.pdf"]

    restored = WikiPage.from_dict(d, body="Hello world")
    assert restored.id == "abc"
    assert restored.type == PageType.ENTITY
    assert restored.body == "Hello world"


def test_review_item_normalized_title():
    item = make_review_item(
        item_id="rev-1", type_="missing-page",
        title="Missing page: Foo",
        detail="...", confidence=0.9,
    )
    assert item.normalized_title == "missing page: foo"
    assert item.status == "open"


def test_wiki_page_defaults():
    p = WikiPage(id="x", title="X", type=PageType.SOURCE)
    assert p.sources == []
    assert p.created_at == 0
    assert p.body == ""
