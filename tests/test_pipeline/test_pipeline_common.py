"""Tests for src/pipeline/_pipeline_common.py — clean_source_text and helpers."""
from src.pipeline._pipeline_common import clean_source_text


def test_clean_source_text_strips_zero_width_chars():
    """Zero-width characters (ZWSP, ZWNJ, ZWJ, BOM) are removed."""
    assert "\u200b" not in clean_source_text("hello\u200bworld")
    assert "\ufeff" not in clean_source_text("\ufeffBOM text")
    assert "hello" in clean_source_text("hello\u200bworld")
    assert "BOM text" in clean_source_text("\ufeffBOM text")


def test_clean_source_text_collapses_excessive_blank_lines():
    """3+ consecutive blank lines collapsed to 2."""
    result = clean_source_text("line 1\n\n\n\n\nline 2")
    assert "\n\n\n" not in result
    assert "line 1" in result
    assert "line 2" in result


def test_clean_source_text_preserves_two_blank_lines():
    """2 blank lines preserved (valid markdown separator)."""
    result = clean_source_text("a\n\nb")
    assert result.startswith("a\n\nb")


def test_clean_source_text_preserves_all_content():
    """All actual text content survives cleaning."""
    text = "标题\n\n正文内容\n- 列表项 1\n- 列表项 2\n\n结尾"
    result = clean_source_text(text)
    assert "标题" in result
    assert "正文内容" in result
    assert "列表项 1" in result
    assert "列表项 2" in result
    assert "结尾" in result


def test_clean_source_text_empty_input():
    """Empty or whitespace-only input returns empty string."""
    assert clean_source_text("") == ""
    assert clean_source_text("   \n  ") == ""


def test_clean_source_text_adds_trailing_newline():
    """Non-empty result always ends with a single newline."""
    result = clean_source_text("hello")
    assert result.endswith("\n")
    assert not result.endswith("\n\n")


def test_clean_source_text_handles_mixed_whitespace():
    """Blank lines with spaces/tabs collapsed correctly — 4 blank lines → 2."""
    text = "a\n \n\t\n   \nb"
    result = clean_source_text(text)
    # 3+ consecutive blank lines (each containing only spaces/tabs) collapsed to 2.
    # The text after the collapse area ("   \nb") is preserved.
    assert "a" in result
    assert "b" in result
    assert "\n\n\n" not in result  # no 3-consecutive blank lines
