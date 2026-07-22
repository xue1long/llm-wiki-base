"""Tests for src.wiki.wikilink."""
from src.wiki.features.wikilink import (
    WIKILINK_PATTERN, create_stub_if_missing, extract_wikilinks, resolve_wikilink,
)
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page


def test_wikilink_pattern_no_alias():
    matches = WIKILINK_PATTERN.findall("see [[foo]]")
    assert matches == [("foo", "")]


def test_wikilink_pattern_with_alias():
    matches = WIKILINK_PATTERN.findall("see [[bar|baz]]")
    assert matches == [("bar", "baz")]


def test_extract_wikilinks_strips_alias():
    text = "see [[foo]] and [[bar|baz]] and [[qux]]"
    assert extract_wikilinks(text) == ["foo", "bar", "qux"]


def test_resolve_wikilink_finds_entity(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="foo", title="Foo", type=PageType.ENTITY))

    assert resolve_wikilink(tmp_path, "foo") is True
    assert resolve_wikilink(tmp_path, "missing") is False


def test_create_stub_if_missing(tmp_path):
    ensure_knowledge_base(tmp_path)
    stub_path = create_stub_if_missing(tmp_path, "pending-concept")
    assert stub_path is not None
    # stub_path IS the path to the created stub file.
    assert stub_path.exists()
    assert stub_path.name == "pending-concept.md"
    assert "stubs" in str(stub_path).replace("\\", "/")
    # Re-creating is a no-op (returns None).
    assert create_stub_if_missing(tmp_path, "pending-concept") is None


def test_create_stub_does_not_clobber_real_page(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="alpha", title="Alpha", type=PageType.ENTITY))
    # Should NOT overwrite — returns None since resolve returns True.
    result = create_stub_if_missing(tmp_path, "alpha")
    assert result is None
    # Alpha still in entities, not in stubs.
    assert (p.wiki_entities / "alpha.md").exists()
    assert not (p.wiki_stubs / "alpha.md").exists()
