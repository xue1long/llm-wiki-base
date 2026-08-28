# tests/test_collector/test_collector.py
"""Task 7: 顶层编排器 Collector + raw_writer 测试。"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.collector.collector import Collector
from src.collector.converter.base import ConvertResult
from src.collector.converter.exceptions import UnsupportedSourceError
from src.collector.writer.raw_writer import write_to_raw, _sanitize_filename


# ---------------------------------------------------------------------------
# raw_writer
# ---------------------------------------------------------------------------


class TestRawWriter:
    """write_to_raw 将 ConvertResult 写入 raw/sources/。"""

    def test_write_text_file(self, tmp_path):
        """写入文本类型的 Markdown。"""
        raw_dir = tmp_path / "raw" / "sources"
        raw_dir.mkdir(parents=True)

        result = ConvertResult(
            content="# Hello\n\nWorld",
            title="Hello",
            source_type="text",
        )
        rel = write_to_raw(result, tmp_path)

        assert rel.startswith("raw/sources/")
        written = tmp_path / rel
        assert written.exists()
        assert written.read_text(encoding="utf-8") == "# Hello\n\nWorld"

    def test_write_with_custom_filename(self, tmp_path):
        """自定义文件名。"""
        raw_dir = tmp_path / "raw" / "sources"
        raw_dir.mkdir(parents=True)

        result = ConvertResult(content="content", title="T", source_type="md")
        rel = write_to_raw(result, tmp_path, filename="custom.md")

        assert rel == "raw/sources/custom.md"
        assert (tmp_path / rel).exists()

    @pytest.mark.parametrize("filename", ["../escape.md", "nested/escape.md", "C:/escape.md"])
    def test_write_rejects_custom_filename_outside_raw_sources(self, tmp_path, filename):
        result = ConvertResult(content="content", title="T", source_type="md")

        with pytest.raises(ValueError, match="basename"):
            write_to_raw(result, tmp_path, filename=filename)

    def test_write_image_with_raw_bytes(self, tmp_path):
        """图片类型：写原始图片 + 描述 .md。"""
        raw_dir = tmp_path / "raw" / "sources"
        raw_dir.mkdir(parents=True)

        result = ConvertResult(
            content="# Photo\n\nDescription",
            title="photo",
            source_type="image",
            metadata={"format": "png"},
            raw_bytes=b"\x89PNGfake",
        )
        rel = write_to_raw(result, tmp_path)

        assert rel.endswith(".md")
        assert (tmp_path / rel).exists()
        # 原始图片也应保存
        img_path = raw_dir / "photo.png"
        assert img_path.exists()
        assert img_path.read_bytes() == b"\x89PNGfake"

    def test_write_creates_directory(self, tmp_path):
        """raw/sources/ 不存在时自动创建。"""
        result = ConvertResult(content="body", title="test", source_type="md")
        rel = write_to_raw(result, tmp_path)
        assert (tmp_path / rel).exists()

    def test_sanitize_filename(self):
        """清理非法字符。"""
        assert _sanitize_filename("hello world") == "hello world"
        assert _sanitize_filename('file<>:"/\\|?*name') == "filename"
        assert _sanitize_filename("") == "untitled"
        assert _sanitize_filename("a" * 200)[:120] == "a" * 120


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class TestCollector:
    """Collector 顶层编排器。"""

    def test_init(self, tmp_path):
        """构造器正常初始化。"""
        c = Collector(project_root=tmp_path)
        assert c.project_root == tmp_path
        assert c.llm_provider is None
        assert len(c._converters) > 0

    def test_init_with_provider(self, tmp_path):
        """带 LLM Provider 构造。"""
        provider = MagicMock()
        c = Collector(project_root=tmp_path, llm_provider=provider)
        assert c.llm_provider is provider

    def test_find_converter_pdf(self, tmp_path):
        """找到 PDF 转换器。"""
        c = Collector(project_root=tmp_path)
        conv = c._find_converter("report.pdf")
        assert conv is not None
        assert conv.can_handle("report.pdf") is True

    def test_find_converter_url(self, tmp_path):
        """找到 URL 转换器。"""
        c = Collector(project_root=tmp_path)
        conv = c._find_converter("https://example.com")
        assert conv is not None

    def test_find_converter_image(self, tmp_path):
        """找到图片转换器。"""
        c = Collector(project_root=tmp_path)
        conv = c._find_converter("photo.jpg")
        assert conv is not None

    def test_find_converter_unknown(self, tmp_path):
        """未知格式返回 None。"""
        c = Collector(project_root=tmp_path)
        conv = c._find_converter("file.xyz")
        assert conv is None

    @pytest.mark.asyncio
    async def test_collect_unsupported(self, tmp_path):
        """不支持的格式抛出 UnsupportedSourceError。"""
        c = Collector(project_root=tmp_path)
        with pytest.raises(UnsupportedSourceError):
            await c.collect("file.xyz")

    @pytest.mark.asyncio
    async def test_collect_txt(self, tmp_path):
        """采集 TXT 文件。"""
        c = Collector(project_root=tmp_path)
        result = await c.collect("notes.txt", content=b"Hello World")

        assert result.source_type == "text"
        assert result.title == "Hello World"
        assert "Hello World" in result.content
        # 文件已写入 raw/sources/
        assert result.original_path.startswith("raw/sources/")
        assert (tmp_path / result.original_path).exists()

    @pytest.mark.asyncio
    async def test_collect_md(self, tmp_path):
        """采集 MD 文件。"""
        c = Collector(project_root=tmp_path)
        md = "# Title\n\nBody content."
        result = await c.collect("doc.md", content=md.encode())

        assert result.source_type == "md"
        assert result.title == "Title"

    @pytest.mark.asyncio
    async def test_collect_image_no_provider(self, tmp_path):
        """无 LLM 时采集图片，降级到元数据。"""
        c = Collector(project_root=tmp_path, llm_provider=None)
        result = await c.collect("photo.png", content=b"\x89PNGfake")

        assert result.source_type == "image"
        assert result.metadata["ocr_method"] == "fallback"
        assert "未配置 LLM Vision" in result.content

    @pytest.mark.asyncio
    async def test_collect_image_with_provider(self, tmp_path):
        """有 LLM 时采集图片，调用 Vision API。"""
        mock_provider = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "图片中的文字"
        mock_provider.complete.return_value = mock_response

        c = Collector(project_root=tmp_path, llm_provider=mock_provider)
        result = await c.collect("screenshot.png", content=b"\x89PNGfake")

        assert result.source_type == "image"
        assert result.metadata["ocr_method"] == "llm_vision"
        assert "图片中的文字" in result.content
