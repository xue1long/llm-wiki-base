# tests/test_collector/test_pdf_converter.py
"""Task 2: PDF 转换器测试。"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from src.collector.converter.pdf_converter import PdfConverter
from src.collector.converter.base import ConvertResult


class TestPdfConverter:
    """PdfConverter 将 PDF 转换为结构化 Markdown。"""

    def setup_method(self):
        self.converter = PdfConverter()

    # -- can_handle --

    def test_can_handle_pdf(self):
        assert self.converter.can_handle("report.pdf") is True

    def test_can_handle_pdf_uppercase(self):
        assert self.converter.can_handle("REPORT.PDF") is True

    def test_can_handle_path(self):
        assert self.converter.can_handle(Path("/docs/report.pdf")) is True

    def test_cannot_handle_docx(self):
        assert self.converter.can_handle("report.docx") is False

    def test_cannot_handle_txt(self):
        assert self.converter.can_handle("report.txt") is False

    # -- convert --

    @pytest.mark.asyncio
    async def test_convert_from_bytes(self):
        """convert 接受 bytes 输入（模拟上传场景）。"""
        mock_text = "<!-- page: 1 -->\nHello World\n\n<!-- page: 2 -->\nSecond page"

        with patch(
            "src.collector.converter.pdf_converter.extract_pdf_text",
            return_value=mock_text,
        ):
            result = await self.converter.convert(
                "test.pdf", content=b"fake pdf bytes"
            )

        assert isinstance(result, ConvertResult)
        assert result.source_type == "pdf"
        assert result.title == "test"
        assert "# test" in result.content
        assert "第 1 页" in result.content
        assert "第 2 页" in result.content
        assert "Hello World" in result.content
        assert result.metadata["pages"] == 2

    @pytest.mark.asyncio
    async def test_convert_from_path(self):
        """convert 接受文件路径输入。"""
        mock_text = "<!-- page: 1 -->\nContent here"

        with patch(
            "src.collector.converter.pdf_converter.extract_pdf_text",
            return_value=mock_text,
        ):
            result = await self.converter.convert("/docs/report.pdf")

        assert result.title == "report"
        assert "# report" in result.content
        assert result.metadata["pages"] == 1

    @pytest.mark.asyncio
    async def test_convert_single_page(self):
        """单页 PDF 没有 page 标注时也正常工作。"""
        mock_text = "Simple document with no page markers"

        with patch(
            "src.collector.converter.pdf_converter.extract_pdf_text",
            return_value=mock_text,
        ):
            result = await self.converter.convert("simple.pdf")

        assert "# simple" in result.content
        assert "Simple document" in result.content
        assert result.metadata["pages"] == 0
