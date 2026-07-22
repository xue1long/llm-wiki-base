"""Tests for src/wiki/tag_namespace.py."""
from src.wiki.tag_namespace import TAG_PREFIXES, is_valid, parse, validate_tags


def test_valid():
    """Valid tags use one of 8 controlled prefixes."""
    assert is_valid("genre/noir")
    assert is_valid("func/storage")
    assert is_valid("char/hero")
    assert is_valid("event/climax")
    assert is_valid("mood/somber")
    assert is_valid("entity/database")
    assert is_valid("scene_phase/intro")
    assert is_valid("status/active")
    # All 8 prefixes registered
    assert len(TAG_PREFIXES) == 8


def test_invalid():
    """Tags without controlled prefix are invalid."""
    assert not is_valid("foo/bar")
    assert not is_valid("nope")
    assert not is_valid("")
    assert not is_valid("genre-no-slash")
    assert not is_valid("/no-prefix")


def test_parse():
    """parse() returns (prefix, name) for valid tags, None for invalid."""
    assert parse("genre/noir") == ("genre", "noir")
    assert parse("scene_phase/intro") == ("scene_phase", "intro")
    assert parse("foo/bar") is None
    assert parse("no-slash") is None


def test_validate_tags_returns_invalid():
    """validate_tags returns list of invalid tags."""
    tags = ["genre/noir", "foo/bar", "entity/db", "", "mood"]
    invalid = validate_tags(tags)
    assert invalid == ["foo/bar", "", "mood"]
