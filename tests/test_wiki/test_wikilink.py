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


# ---------------------------------------------------------------------------
# P1 follow-up: resolve_wikilink falls back through the slug alias registry.
# Production evidence (novel-wiki 2026-07-26): ``qi-dai-gan`` should
# resolve to canonical ``qi-dai-gan-chuangzuo`` via the alias table.
# ---------------------------------------------------------------------------


def test_resolve_wikilink_via_alias_registered(tmp_path):
    """When the canonical page exists AND an alias maps the lookup
    target to it, resolve_wikilink returns True (alias chain hit).
    """
    from src.wiki.features.slug_aliases import SlugAliasRegistry
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="qi-dai-gan-chuangzuo",
                            title="期待感创作", type=PageType.CONCEPT))
    # Pre-register the alias
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.save()

    # Exact target miss; alias chain should still find the page.
    assert resolve_wikilink(tmp_path, "qi-dai-gan") is True


def test_resolve_wikilink_alias_chains_to_missing_target(tmp_path):
    """If alias maps to a slug that has no on-disk page, resolution
    is False. (Alias chain only helps when canonical exists.)
    """
    from src.wiki.features.slug_aliases import SlugAliasRegistry
    ensure_knowledge_base(tmp_path)
    reg = SlugAliasRegistry(tmp_path)
    reg.add("orphan-alias", "no-such-page")
    reg.save()
    assert resolve_wikilink(tmp_path, "orphan-alias") is False


def test_resolve_wikilink_no_alias_no_page(tmp_path):
    """Without an alias mapping and without an on-disk page,
    resolution is False — backwards compatible with original behavior.
    """
    ensure_knowledge_base(tmp_path)
    assert resolve_wikilink(tmp_path, "completely-unknown") is False


def test_resolve_wikilink_exact_match_takes_priority_over_alias(tmp_path):
    """If a real page exists at the exact name AND there's an unrelated
    alias elsewhere, the exact-match wins (no regression vs. original
    exact-match semantics).
    """
    from src.wiki.features.slug_aliases import SlugAliasRegistry
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="real-target", title="R", type=PageType.ENTITY))
    reg = SlugAliasRegistry(tmp_path)
    reg.add("real-target", "different-canonical")  # contradictory
    reg.save()
    assert resolve_wikilink(tmp_path, "real-target") is True
