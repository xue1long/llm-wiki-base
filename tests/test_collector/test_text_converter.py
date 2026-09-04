# tests/test_collector/test_text_converter.py
"""Task 4: Text 转换器测试。"""
from __future__ import annotations

import pytest

from src.collector.converter.text_converter import TextConverter
from src.collector.converter.base import ConvertResult


class TestTextConverter:
    """TextConverter 将 TXT/MD 转换为 Markdown。"""

    def setup_method(self):
        self.converter = TextConverter()

    # -- can_handle --

    def test_can_handle_txt(self):
        assert self.converter.can_handle("notes.txt") is True

    def test_can_handle_md(self):
        assert self.converter.can_handle("readme.md") is True

    def test_can_handle_markdown(self):
        assert self.converter.can_handle("doc.markdown") is True

    def test_cannot_handle_pdf(self):
        assert self.converter.can_handle("report.pdf") is False

    def test_cannot_handle_docx(self):
        assert self.converter.can_handle("report.docx") is False

    # -- convert TXT --

    @pytest.mark.asyncio
    async def test_convert_txt_from_bytes(self):
        """TXT bytes 输入，提取首行作为标题。"""
        text = b"Chapter One\n\nThis is the content."
        result = await self.converter.convert("notes.txt", content=text)

        assert isinstance(result, ConvertResult)
        assert result.source_type == "text"
        assert result.title == "Chapter One"
        assert "# Chapter One" in result.content
        assert "This is the content." in result.content

    @pytest.mark.asyncio
    async def test_convert_txt_no_title(self):
        """空文本使用文件名作为标题。"""
        result = await self.converter.convert("empty.txt", content=b"")

        assert result.title == "empty"
        assert "# empty" in result.content

    # -- convert MD --

    @pytest.mark.asyncio
    async def test_convert_md_passthrough(self):
        """MD 文件原样保留，不加额外标题头。"""
        md_text = "# My Title\n\nBody content with **bold**."
        result = await self.converter.convert("doc.md", content=md_text.encode())

        assert result.source_type == "md"
        assert result.title == "My Title"
        # MD 原样，不额外包裹
        assert result.content == md_text

    @pytest.mark.asyncio
    async def test_convert_md_with_hash_title(self):
        """MD 文件标题从 # 行提取。"""
        md = "# Project Plan\n\n## Step 1\n\nDetails here."
        result = await self.converter.convert("plan.md", content=md.encode())

        assert result.title == "Project Plan"

    @pytest.mark.asyncio
    async def test_convert_md_without_hash_title(self):
        """MD 文件没有 # 标题时，用首行非空文本。"""
        md = "Introduction paragraph\n\nMore content."
        result = await self.converter.convert("doc.md", content=md.encode())

        assert result.title == "Introduction paragraph"
