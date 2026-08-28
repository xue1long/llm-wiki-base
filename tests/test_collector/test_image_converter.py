# tests/test_collector/test_image_converter.py
"""Task 5: 图片转换器测试。"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.collector.converter.image_converter import ImageConverter
from src.collector.converter.base import ConvertResult


class TestImageConverter:
    """ImageConverter 将图片转换为 Markdown。"""

    # -- can_handle --

    def test_can_handle_jpg(self):
        c = ImageConverter()
        assert c.can_handle("photo.jpg") is True

    def test_can_handle_png(self):
        c = ImageConverter()
        assert c.can_handle("screenshot.png") is True

    def test_can_handle_webp(self):
        c = ImageConverter()
        assert c.can_handle("image.webp") is True

    def test_can_handle_gif(self):
        c = ImageConverter()
        assert c.can_handle("animation.gif") is True

    def test_cannot_handle_pdf(self):
        c = ImageConverter()
        assert c.can_handle("doc.pdf") is False

    def test_cannot_handle_txt(self):
        c = ImageConverter()
        assert c.can_handle("notes.txt") is False

    # -- convert with LLM --

    @pytest.mark.asyncio
    async def test_convert_with_vision(self):
        """有 LLM Provider 时调用 Vision API。"""
        mock_provider = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "图片中包含文字：Hello World\n\n这是一个测试图片。"
        mock_provider.complete.return_value = mock_response

        c = ImageConverter(llm_provider=mock_provider)
        # 1x1 红色 PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        result = await c.convert("test.png", content=png_bytes)

        assert isinstance(result, ConvertResult)
        assert result.source_type == "image"
        assert result.title == "test"
        assert "# test" in result.content
        assert "Hello World" in result.content
        assert result.metadata["ocr_method"] == "llm_vision"
        assert result.raw_bytes == png_bytes
        mock_provider.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_convert_vision_failure_fallback(self):
        """Vision API 失败时降级到元数据。"""
        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = Exception("API error")

        c = ImageConverter(llm_provider=mock_provider)
        result = await c.convert("photo.jpg", content=b"\xff\xd8\xff\xe0fake jpg")

        assert result.source_type == "image"
        assert result.metadata["ocr_method"] == "fallback"
        assert "未配置 LLM Vision" in result.content
        assert result.raw_bytes is not None

    # -- convert without LLM --

    @pytest.mark.asyncio
    async def test_convert_no_provider(self):
        """无 LLM Provider 时直接降级。"""
        c = ImageConverter(llm_provider=None)
        result = await c.convert("screenshot.png", content=b"\x89PNGfake")

        assert result.source_type == "image"
        assert result.title == "screenshot"
        assert result.metadata["ocr_method"] == "fallback"
        assert "未配置 LLM Vision" in result.content
        assert "手动描述" in result.content

    @pytest.mark.asyncio
    async def test_convert_from_path(self):
        """从文件路径读取（需要文件存在）。"""
        import tempfile, os

        c = ImageConverter(llm_provider=None)
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNGfake")
            tmp_path = f.name

        try:
            result = await c.convert(tmp_path)
            assert result.source_type == "image"
            assert Path(result.original_path) == Path(tmp_path)
        finally:
            os.unlink(tmp_path)
