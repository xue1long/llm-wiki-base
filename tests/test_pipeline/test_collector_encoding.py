"""Tests for Collector encoding tolerance — _decode_text_file + _repair_double_encoding."""
import pytest
from src.pipeline.collector import _decode_text_file, _repair_double_encoding


class TestDecodeTextFileUTF8:
    def test_utf8_fast_path(self):
        text = "这是一段正常的中文文本。"
        raw = text.encode("utf-8")
        result = _decode_text_file(raw, "test.md")
        assert result == text

    def test_utf8_ascii(self):
        text = "Hello, world!"
        raw = text.encode("utf-8")
        result = _decode_text_file(raw, "test.txt")
        assert result == text


class TestDecodeTextFileGBK:
    def test_gbk_fallback(self):
        text = "手机移动端开发指南"
        raw = text.encode("gbk")
        result = _decode_text_file(raw, "test.md")
        assert result == text

    def test_gb2312_fallback(self):
        text = "中文简体内容"
        raw = text.encode("gb2312")
        result = _decode_text_file(raw, "test.txt")
        assert result == text

    def test_big5_fallback(self):
        text = "繁體中文內容測試"
        raw = text.encode("big5")
        result = _decode_text_file(raw, "test.md")
        assert result == text


class TestRepairDoubleEncoding:
    def test_gbk_double_encoding_repair(self):
        """GBK→latin-1→UTF-8 double-encoded text is repaired."""
        original = "手机移动端开发指南手册"
        gbk_bytes = original.encode("gbk")
        double_encoded = gbk_bytes.decode("latin-1")
        # Verify it's NOT the original (mojibake)
        assert double_encoded != original
        # Repair should recover it
        repaired = _repair_double_encoding(double_encoded)
        assert repaired == original

    def test_big5_double_encoding_repair(self):
        """Big5→latin-1→UTF-8 double-encoded text is repaired."""
        original = "繁體中文操作手冊"
        big5_bytes = original.encode("big5")
        double_encoded = big5_bytes.decode("latin-1")
        assert double_encoded != original
        repaired = _repair_double_encoding(double_encoded)
        assert repaired == original

    def test_utf8_file_with_double_encoded_content(self):
        """Full round-trip: _decode_text_file detects and repairs double encoding."""
        original = "手机移动端开发指南"
        gbk_bytes = original.encode("gbk")
        double_encoded = gbk_bytes.decode("latin-1")
        raw = double_encoded.encode("utf-8")
        result = _decode_text_file(raw, "test.md")
        assert result == original


class TestRepairDoubleEncodingNoFalsePositives:
    def test_french_text_not_repaired(self):
        """French text has high Latin-1 BUT also high ASCII — not double-encoded."""
        text = "éàçù Très bien, voilà le café français"
        raw = text.encode("utf-8")
        result = _decode_text_file(raw, "french.md")
        # Should pass through unchanged (French text, not CJK double-encoding)
        # The ASCII density >15% precondition blocks the repair
        assert result == text

    def test_normal_chinese_not_repaired(self):
        """Normal Chinese has low Latin-1 Supplement — precondition fails."""
        text = "这是一段正常的中文文本，不需要修复。"
        raw = text.encode("utf-8")
        result = _decode_text_file(raw, "normal.md")
        assert result == text

    def test_short_text_not_repaired(self):
        """Text < 15 chars is too short for double-encoding detection."""
        text = "短文本"
        raw = text.encode("utf-8")
        result = _decode_text_file(raw, "short.md")
        assert result == text


class TestDecodeTextFileErrors:
    def test_all_encodings_fail(self):
        """Random bytes that match no encoding raise ValueError."""
        raw = bytes(range(256))
        with pytest.raises(ValueError, match="Cannot decode"):
            _decode_text_file(raw, "binary.bin")


class TestRepairDoubleEncodingEdgeCases:
    def test_returns_none_for_normal_text(self):
        """Normal UTF-8 text returns None (no repair needed)."""
        assert _repair_double_encoding("Hello world") is None
        assert _repair_double_encoding("正常中文") is None

    def test_returns_none_for_empty(self):
        assert _repair_double_encoding("") is None

    def test_gbk_best_score_wins(self):
        """When both GBK and Big5 round-trips produce CJK, highest yield wins."""
        original = "操作系统内核设计与实现"
        gbk_bytes = original.encode("gbk")
        double_encoded = gbk_bytes.decode("latin-1")
        repaired = _repair_double_encoding(double_encoded)
        assert repaired == original
