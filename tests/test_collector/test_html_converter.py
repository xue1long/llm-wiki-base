# tests/test_collector/test_html_converter.py
"""Task 4: HTML 转换器测试。"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from src.collector.converter.html_converter import HtmlConverter
from src.collector.converter.base import ConvertResult


class TestHtmlConverter:
    """HtmlConverter 将 HTML 转换为 Markdown。"""

    def setup_method(self):
        self.converter = HtmlConverter()

    # -- can_handle --

    def test_can_handle_html(self):
        assert self.converter.can_handle("page.html") is True

    def test_can_handle_htm(self):
        assert self.converter.can_handle("page.htm") is True

    def test_cannot_handle_md(self):
        assert self.converter.can_handle("page.md") is False

    # -- title extraction --

    def test_extract_title_from_title_tag(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert self.converter._extract_html_title(html) == "My Page"

    def test_extract_title_from_h1(self):
        html = "<html><body><h1>First Heading</h1><p>Text</p></body></html>"
        assert self.converter._extract_html_title(html) == "First Heading"

    def test_extract_title_empty(self):
        html = "<html><body><p>No title</p></body></html>"
        assert self.converter._extract_html_title(html) == ""

    # -- convert --

    @pytest.mark.asyncio
    async def test_convert_html(self):
        """HTML → Markdown。"""
        html = (
            "<html><head><title>Test Page</title></head>"
            "<body><h1>Hello</h1><p>World</p></body></html>"
        )

        with patch(
            "src.collector.converter.html_converter.html_to_text",
            return_value="Hello\n\nWorld",
        ), patch(
            "src.collector.converter.html_converter.convert_html_tables_to_markdown",
            return_value=html,
        ):
            result = await self.converter.convert("page.html", content=html.encode())

        assert isinstance(result, ConvertResult)
        assert result.source_type == "html"
        assert result.title == "Test Page"
        assert "# Test Page" in result.content
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_convert_html_from_bytes(self):
        """HTML bytes 输入。"""
        html = "<html><head><title>From Bytes</title></head><body>OK</body></html>"

        with patch(
            "src.collector.converter.html_converter.html_to_text",
            return_value="OK",
        ), patch(
            "src.collector.converter.html_converter.convert_html_tables_to_markdown",
            return_value=html,
        ):
            result = await self.converter.convert("test.htm", content=html.encode())

        assert result.title == "From Bytes"
        assert result.metadata["format"] == "html"
