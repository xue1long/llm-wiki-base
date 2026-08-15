"""Tests for src/wiki/id_generator.py + WikiPage v2.2 fields."""
from src.wiki.core.id_generator import (
    generate_page_id,
    is_valid_id,
    normalize_id_chars,
)
from src.wiki.core.types import PageType, WikiPage


def test_normalize_id_chars_fullwidth_parens():
    """Full-width parens （）(batch-50 H4 violations) become '-' and collapse."""
    assert normalize_id_chars("元素化-（-写作问题-）") == "元素化-写作问题"
    assert normalize_id_chars("泰坦-（-普罗米修斯") == "泰坦-普罗米修斯"
    assert is_valid_id(normalize_id_chars("元素化-（-写作问题-）"))


def test_normalize_id_chars_underscore_to_dash():
    """Underscores (from filenames like xxx_7c8873) become '-'."""
    assert normalize_id_chars("大纲示例新人写大纲_7c8873") == "大纲示例新人写大纲-7c8873"
    assert is_valid_id(normalize_id_chars("大纲示例新人写大纲_7c8873"))


def test_normalize_id_chars_lowercases_ascii():
    """Uppercase ASCII is lowercased (kebab-case is lowercase only)."""
    assert normalize_id_chars("Terry-Brooks") == "terry-brooks"
    assert normalize_id_chars("OpenAI-写作") == "openai-写作"
    assert is_valid_id(normalize_id_chars("OpenAI-写作"))


def test_normalize_id_chars_book_brackets_and_misc():
    """Book brackets 《》 and other invalid chars are stripped/normalized."""
    assert normalize_id_chars("《-俄狄浦斯王-》") == "俄狄浦斯王"
    assert normalize_id_chars("　带全角空格　") == "带全角空格"
    assert normalize_id_chars("foo bar  baz") == "foo-bar-baz"


def test_normalize_id_chars_clean_id_unchanged():
    """Already-valid ids pass through unchanged."""
    assert normalize_id_chars("tolkien") == "tolkien"
    assert normalize_id_chars("网络文学") == "网络文学"
    assert normalize_id_chars("写作-ai-网络") == "写作-ai-网络"
    assert normalize_id_chars("") == ""


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


def test_is_valid_id_cjk_basic_block():
    """CJK Unified Ideographs (U+4E00–U+9FFF) are now valid id
    characters after the 2026-07-26 CJK cut-over. The ID_PATTERN
    accepts:

    - pure CJK
    - CJK + ASCII mixes (after slugify normalizes to kebab-case)
    - card_..._UUIDv7 with CJK suffix
    """
    # Pure CJK (basic block)
    assert is_valid_id("网络文学")
    assert is_valid_id("仙侠小说")
    # After slugify, mixed "混Test合" → "混-test-合" (T → t + hyphen
    # at run boundary). Slugified form must be valid.
    assert is_valid_id("混-test-合")
    # CJK + ASCII mixes (already kebab-case)
    assert is_valid_id("ai-写作")
    assert is_valid_id("网络-文学")
    assert is_valid_id("写作-ai-网络")
    # UUIDv7 with CJK suffix
    assert is_valid_id("card_0123456789abc_01234567_网络文学")
    # Pure ASCII kebab-case still works (backwards compat)
    assert is_valid_id("foo-bar")
    # Uppercase ASCII rejected (kebab-case is lowercase only)
    assert not is_valid_id("Test")
    # Multi-line still rejected
    assert not is_valid_id("foo\nbar")
    # Latin extended (é etc.) NOT in CJK cut-over scope; would need
    # a follow-up commit to extend the regex.
    assert not is_valid_id("café")
    # Uppercase CJK is non-existent in Unicode — no need to test.


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
