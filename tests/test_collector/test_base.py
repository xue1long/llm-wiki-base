# tests/test_collector/test_base.py
"""Task 1: ConvertResult / ConverterBase / UnsupportedSourceError."""
from __future__ import annotations

import pytest
from pathlib import Path

from src.collector.converter.base import ConvertResult, ConverterBase
from src.collector.converter.exceptions import UnsupportedSourceError


# ---------------------------------------------------------------------------
# ConvertResult
# ---------------------------------------------------------------------------


class TestConvertResult:
    """ConvertResult 是采集模块的核心数据结构。"""

    def test_minimal_construction(self):
        """最简构造：只需要 content 字段。"""
        r = ConvertResult(content="hello world")
        assert r.content == "hello world"
        assert r.title == ""
        assert r.metadata == {}
        assert r.source_type == "text"
        assert r.original_path == ""
        assert r.raw_bytes is None

    def test_full_construction(self):
        """完整构造：所有字段都有值。"""
        r = ConvertResult(
            content="# Title\n\nBody",
            title="Title",
            metadata={"pages": 5, "author": "test"},
            source_type="pdf",
            original_path="/path/to/file.pdf",
            raw_bytes=b"raw",
        )
        assert r.content == "# Title\n\nBody"
        assert r.title == "Title"
        assert r.metadata["pages"] == 5
        assert r.source_type == "pdf"
        assert r.original_path == "/path/to/file.pdf"
        assert r.raw_bytes == b"raw"

    def test_metadata_default_is_independent(self):
        """每次构造的 metadata 默认值应是独立的 dict。"""
        r1 = ConvertResult(content="a")
        r2 = ConvertResult(content="b")
        r1.metadata["key"] = "value"
        assert "key" not in r2.metadata


# ---------------------------------------------------------------------------
# ConverterBase
# ---------------------------------------------------------------------------


class TestConverterBase:
    """ConverterBase 是抽象类，不能直接实例化。"""

    def test_cannot_instantiate(self):
        """直接实例化应抛出 TypeError。"""
        with pytest.raises(TypeError):
            ConverterBase()  # type: ignore[abstract]

    def test_subclass_must_implement(self):
        """只实现一个方法的子类仍不能实例化。"""

        class Partial(ConverterBase):
            def can_handle(self, source):
                return True

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        """同时实现两个方法的子类可以实例化。"""

        class DummyConverter(ConverterBase):
            def can_handle(self, source):
                return str(source).endswith(".dummy")

            async def convert(self, source, *, content=None):
                return ConvertResult(content="dummy", source_type="dummy")

        c = DummyConverter()
        assert c.can_handle("test.dummy") is True
        assert c.can_handle("test.pdf") is False

    @pytest.mark.asyncio
    async def test_concrete_convert(self):
        """完整子类的 convert 返回 ConvertResult。"""

        class DummyConverter(ConverterBase):
            def can_handle(self, source):
                return True

            async def convert(self, source, *, content=None):
                return ConvertResult(
                    content="converted",
                    title="Test",
                    source_type="dummy",
                )

        c = DummyConverter()
        result = await c.convert("anything")
        assert result.content == "converted"
        assert result.title == "Test"
        assert result.source_type == "dummy"


# ---------------------------------------------------------------------------
# UnsupportedSourceError
# ---------------------------------------------------------------------------


class TestUnsupportedSourceError:
    """UnsupportedSourceError 携带源信息。"""

    def test_with_source(self):
        err = UnsupportedSourceError("test.xyz")
        assert err.source == "test.xyz"
        assert "test.xyz" in str(err)

    def test_with_custom_message(self):
        err = UnsupportedSourceError("test.xyz", "custom msg")
        assert err.source == "test.xyz"
        assert str(err) == "custom msg"

    def test_is_value_error(self):
        """应是 ValueError 的子类，兼容上层捕获。"""
        assert issubclass(UnsupportedSourceError, ValueError)
