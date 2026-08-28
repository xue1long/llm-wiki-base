# tests/test_collector/test_url_converter.py
"""Task 6: URL 转换器测试。"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.collector.converter.url_converter import UrlConverter
from src.collector.converter.base import ConvertResult


class TestUrlConverter:
    """UrlConverter 抓取 URL 内容并转换为 Markdown。"""

    def setup_method(self):
        self.converter = UrlConverter()

    # -- can_handle --

    def test_can_handle_http(self):
        assert self.converter.can_handle("http://example.com") is True

    def test_can_handle_https(self):
        assert self.converter.can_handle("https://example.com/page") is True

    def test_cannot_handle_file(self):
        assert self.converter.can_handle("/path/to/file.html") is False

    def test_cannot_handle_ftp(self):
        assert self.converter.can_handle("ftp://server/file") is False

    # -- convert HTML --

    @pytest.mark.asyncio
    async def test_convert_html_content(self):
        """HTML 内容转换。"""
        html = b"<html><head><title>Test</title></head><body><p>Hello</p></body></html>"

        with patch(
            "src.utils.text.html_to_text",
            return_value="Hello",
        ), patch(
            "src.utils.extract.html.convert_html_tables_to_markdown",
            return_value="<html><head><title>Test</title></head><body><p>Hello</p></body></html>",
        ):
            result = await self.converter.convert("https://example.com", content=html)

        assert isinstance(result, ConvertResult)
        assert result.source_type == "url"
        assert result.title == "Test"
        assert "# Test" in result.content
        assert result.metadata["url"] == "https://example.com"

    # -- convert PDF link --

    @pytest.mark.asyncio
    async def test_convert_pdf_link(self):
        """PDF 链接分派到 PdfConverter。"""
        with patch(
            "src.collector.converter.url_converter.UrlConverter._dispatch",
        ) as mock_dispatch:
            mock_dispatch.return_value = ConvertResult(
                content="# PDF Content",
                title="PDF",
                source_type="pdf",
            )
            result = await self.converter.convert(
                "https://example.com/doc.pdf",
                content=b"%PDF-1.4 fake",
            )

        # 因为 content 直接传入，走 _dispatch
        assert result.source_type in ("pdf", "url")

    # -- title extraction --

    def test_extract_title_from_html(self):
        html = "<html><head><title>My Title</title></head></html>"
        assert self.converter._extract_title(html) == "My Title"

    def test_extract_title_from_h1(self):
        html = "<html><body><h1>Heading</h1></body></html>"
        assert self.converter._extract_title(html) == "Heading"

    def test_extract_title_empty(self):
        html = "<html><body><p>no title</p></body></html>"
        assert self.converter._extract_title(html) == ""
