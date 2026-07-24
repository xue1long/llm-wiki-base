"""Tests for src/wiki/id_generator.py + WikiPage v2.2 fields."""
from src.wiki.core.id_generator import generate_page_id, is_valid_id, ID_PATTERN
from src.wiki.core.types import PageType, WikiPage


def test_generate_id_format():
    """Generated ID matches the UUID v7 + slug pattern."""
    pid = generate_page_id("foo-bar")
    assert pid.startswith("card_")
    assert pid.endswith("_foo-bar")
    assert is_valid_id(pid)
    # Length: 5 (card_) + 13 (millis) + 1 (_) + 8 (rand) + 1 (_) + slug
    # = 28 + len(slug)


def test_is_valid_id():
    """is_valid_id accepts UUID v7 format and legacy pure slugs."""
    assert is_valid_id("card_0123456789abc_01234567_my-slug")
    assert is_valid_id(generate_page_id("test"))
    assert is_valid_id("foo-bar")  # slug now accepted
    assert not is_valid_id("card_xyz_01234567_my-slug")  # invalid hex
    assert not is_valid_id("")


def test_wiki_page_v22_fields():
    """WikiPage has grade/processing_depth/is_immutable fields with defaults."""
    page = WikiPage(id="foo", title="F", type=PageType.ENTITY)
    assert page.grade == "B"
    assert page.processing_depth == "concept"
    assert page.is_immutable is False

    fm = page.to_frontmatter_dict()
    assert fm["grade"] == "B"
    assert fm["processing_depth"] == "concept"
    assert fm["is_immutable"] is False

    restored = WikiPage.from_dict(fm, body="")
    assert restored.grade == "B"
    assert restored.processing_depth == "concept"
    assert restored.is_immutable is False


def test_wiki_page_v22_fields_custom_values():
    """WikiPage accepts custom v2.2 field values."""
    page = WikiPage(
        id="foo", title="F", type=PageType.CONCEPT,
        grade="A", processing_depth="memory", is_immutable=True,
    )
    fm = page.to_frontmatter_dict()
    assert fm["grade"] == "A"
    assert fm["processing_depth"] == "memory"
    assert fm["is_immutable"] is True
    restored = WikiPage.from_dict(fm)
    assert restored.grade == "A"