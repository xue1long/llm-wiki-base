"""Tests for src.utils.slugify — CJK-first slug generation.

After cutting over to CJK (2026-07-26), the slug generator must
preserve Chinese characters rather than transliterate to pinyin.
"""
import unicodedata
import pytest
from src.utils.slugify import slugify, ensure_unique_slug


def test_slugify_pure_cjk_passthrough():
    """Pure CJK input is preserved character-for-character
    (after NFC normalize), no transliteration.
    """
    assert slugify("网络文学") == "网络文学"
    assert slugify("仙侠小说") == "仙侠小说"


def test_slugify_mixed_ascii_lowercased():
    """Pure ASCII input still goes through the kebab-case path:
    lowercase + non-alphanumeric → single hyphen.
    """
    assert slugify("Hello World!") == "hello-world"
    assert slugify("OpenAI") == "openai"


def test_slugify_mixed_cjk_and_ascii_joined_by_hyphen():
    """Mixed scripts get separate runs joined by a hyphen; each
    run goes through its own path. No pinyin conversion.
    """
    assert slugify("混Test合") == "混-test-合"
    assert slugify("AI写作") == "ai-写作"


def test_slugify_strips_whitespace_and_collapses_hyphens():
    """Edge cases: empty input, whitespace-only, double-hyphen
    artifacts. Behavior unchanged from the previous version.
    """
    assert slugify("") == ""
    assert slugify("   ") == ""
    assert slugify(None) == ""
    assert slugify("foo--bar") == "foo-bar"
    assert slugify("  hello world  ") == "hello-world"


def test_slugify_nfc_normalizes_nfd_input():
    """NFD-encoded input (combining marks split from base char)
    is normalized to NFC so we don't end up with two slugs for
    one concept (the macOS HFS+ NFD pitfall).
    """
    nfd = "café"  # default 'café' is NFC; this can be NFD via ...
    nfd_combined = unicodedata.normalize("NFD", nfd)
    # Construct an input that, if not normalized, would diverge.
    nfd_e = "café"  # e + combining acute (NFD)
    nfc_e = unicodedata.normalize("NFC", nfd_e)
    # After NFC, both should slugify to the same thing.
    assert unicodedata.normalize("NFC", slugify(nfd_e)) == slugify(nfc_e)
    # And explicitly: e + combining mark should normalize to é before slug.
    assert slugify(nfd_e) == unicodedata.normalize("NFC", nfd_e)


def test_slugify_does_not_transliterate_cjk():
    """CJK characters stay as-is, never become pinyin. This is
    the CJK cut-over: removes pypinyin dependency from slugify.
    """
    # If pypinyin were still active, these would become pinyin
    # strings. With CJK cut-over, they are preserved.
    assert "wangluo" not in slugify("网络文学")
    assert "xianxia" not in slugify("仙侠小说")
    assert "pinyin" not in slugify("拼音")


def test_slugify_ensure_unique_still_works():
    """ensure_unique_slug() must still dedupe by appending -2, -3...
    because two distinct concepts can now slugify to the same CJK
    string too (e.g. both '网络' and '网络-' could collapse to '网络').
    """
    taken = {"网络"}
    assert ensure_unique_slug("网络", taken) == "网络-2"
    taken.add("网络-2")
    assert ensure_unique_slug("网络", taken) == "网络-3"


def test_slugify_handles_punctuation_between_cjk():
    """CJK runs survive punctuation that becomes a hyphen."""
    # '网络/文学' → '网络' + '/' + '文学' → each CJK, joined by '-'
    # The '/' goes through the ASCII path → empty → filtered.
    out = slugify("网络/文学")
    assert out  # non-empty
    assert "/" not in out


def test_slugify_cjk_leading_trailing_hyphens_are_stripped():
    """Leading/trailing hyphens from empty ASCII runs around CJK terms
    are stripped so that slugify('-家庭烧伤处理-') matches
    slugify('家庭烧伤处理'). Prevents duplicate entity stubs for
    concepts that already have pages (Fix E dedup).
    """
    assert slugify("-家庭烧伤处理-") == slugify("家庭烧伤处理")
    assert slugify("家庭烧伤处理") == "家庭烧伤处理"
    # Existing behavior must be preserved
    assert slugify("hello-world") == "hello-world"
    assert slugify("混Test合") == "混-test-合"


def test_slugify_brackets_and_quotes_safe_for_wikilinks():
    """Slug output must not contain [[ ]] which would break the
    wikilink ``[[...]]`` parser. Apostrophes, quotes, brackets
    get stripped/converted to hyphens.
    """
    assert "[" not in slugify("foo [bar]")
    assert "]" not in slugify("foo [bar]")
    assert "网络[" not in slugify("网络[文]")
