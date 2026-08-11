"""Tests for src/pipeline/sanitizer.py — SanitizerResult + sanitize()."""
from src.pipeline.sanitizer import sanitize, SanitizerResult, SANITIZER_MAX_CHARS


class TestSanitizeNormalText:
    def test_normal_utf8_chinese_scores_high(self):
        result = sanitize("这是一段正常的中文文本，用于测试质量评分系统。")
        assert result.quality_score >= 0.9
        assert result.warnings == []
        assert result.should_skip_llm is False

    def test_normal_english_scores_high(self):
        result = sanitize("This is a normal English paragraph with proper content.")
        assert result.quality_score >= 0.9
        assert result.warnings == []

    def test_short_meaningful_text_not_skipped(self):
        """8 chars — short but not empty, should NOT be skipped."""
        result = sanitize("Short quote here.")
        assert result.should_skip_llm is False


class TestSanitizeGarbled:
    def test_high_replacement_char_ratio(self):
        """U+FFFD ratio > 1% triggers has_replacement_chars warning + score penalty."""
        text = "�" * 50 + "some valid text"
        result = sanitize(text)
        assert "has_replacement_chars" in result.warnings
        assert result.quality_score < 0.9

    def test_very_high_replacement_char_triggers_garbled(self):
        """U+FFFD ratio > 5% triggers garbled warning."""
        text = "�" * 500 + "tiny"
        result = sanitize(text)
        assert "garbled" in result.warnings
        assert result.quality_score < 0.5

    def test_garbled_text_skips_llm(self):
        """U+FFFD ratio > 30% triggers should_skip_llm."""
        text = "�" * 100
        result = sanitize(text)
        assert result.should_skip_llm is True


class TestSanitizeBlankLines:
    def test_mostly_blank_lines(self):
        """>60% blank lines triggers mostly_blank warning."""
        lines = ["content"] + [""] * 20
        result = sanitize("\n".join(lines))
        assert "mostly_blank" in result.warnings
        assert result.quality_score < 0.9

    def test_normal_paragraph_spacing_ok(self):
        """Normal markdown with single blank lines between paragraphs is fine."""
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
        result = sanitize(text)
        assert "mostly_blank" not in result.warnings
        assert result.quality_score >= 0.9


class TestSanitizeRepetition:
    def test_high_repetition(self):
        """>30% repeated lines triggers high_repetition warning."""
        lines = ["repeat me"] * 50 + ["unique 1", "unique 2"]
        result = sanitize("\n".join(lines))
        assert "high_repetition" in result.warnings
        assert result.quality_score < 0.9

    def test_repeated_lines_collapsed(self):
        """Lines appearing >10 times are collapsed to first occurrence."""
        lines = ["unique header"] + ["repeated"] * 20 + ["unique footer"]
        text = "\n".join(lines)
        result = sanitize(text)
        assert result.text.count("repeated") < text.count("repeated")


class TestSanitizeEmpty:
    def test_empty_string(self):
        result = sanitize("")
        assert result.should_skip_llm is True

    def test_very_short_text_skips(self):
        """<5 chars stripped → should_skip_llm."""
        result = sanitize("abc")
        assert result.should_skip_llm is True

    def test_short_with_high_blanks_skips(self):
        """<20 chars stripped + >90% blanks → should_skip_llm."""
        result = sanitize("hi\n\n\n\n\n\n\n")
        assert result.should_skip_llm is True


class TestSanitizeNormalization:
    def test_zero_width_chars_removed(self):
        result = sanitize("hello​world")
        assert "​" not in result.text

    def test_crlf_converted_to_lf(self):
        result = sanitize("line1\r\nline2")
        assert "\r\n" not in result.text
        assert "line1\nline2" in result.text

    def test_excessive_blank_lines_collapsed(self):
        result = sanitize("a\n\n\n\n\nb")
        assert "\n\n\n" not in result.text

    def test_nfc_normalization(self):
        # NFD 'e' + combining acute → NFC 'é'
        result = sanitize("café")
        assert "é" in result.text


class TestSanitizeLargeText:
    def test_large_text_only_analyzes_window(self):
        """Text > SANITIZER_MAX_CHARS only analyzes the first window."""
        large = "x" * (SANITIZER_MAX_CHARS + 10000)
        result = sanitize(large)
        assert result.quality_score >= 0.9  # all 'x', no noise


class TestSanitizeResultType:
    def test_returns_sanitizer_result(self):
        result = sanitize("test")
        assert isinstance(result, SanitizerResult)
        assert isinstance(result.text, str)
        assert isinstance(result.quality_score, float)
        assert isinstance(result.warnings, list)
        assert isinstance(result.should_skip_llm, bool)
