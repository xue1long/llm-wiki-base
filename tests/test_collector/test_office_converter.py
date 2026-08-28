# tests/test_collector/test_office_converter.py
"""Task 3: Office 转换器测试。"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.collector.converter.office_converter import OfficeConverter
from src.collector.converter.base import ConvertResult


class TestOfficeConverter:
    """OfficeConverter 将 DOCX/XLSX 转换为 Markdown。"""

    def setup_method(self):
        self.converter = OfficeConverter()

    # -- can_handle --

    def test_can_handle_docx(self):
        assert self.converter.can_handle("report.docx") is True

    def test_can_handle_xlsx(self):
        assert self.converter.can_handle("data.xlsx") is True

    def test_cannot_handle_legacy_xls(self):
        """openpyxl cannot read the legacy OLE workbook format."""
        assert self.converter.can_handle("old.xls") is False

    def test_cannot_handle_pdf(self):
        assert self.converter.can_handle("report.pdf") is False

    def test_cannot_handle_txt(self):
        assert self.converter.can_handle("notes.txt") is False

    # -- convert DOCX --

    @pytest.mark.asyncio
    async def test_convert_docx(self):
        """DOCX → Markdown 段落保留。"""
        mock_text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

        with patch(
            "src.collector.converter.office_converter.extract_docx_text",
            return_value=mock_text,
        ):
            result = await self.converter.convert("report.docx")

        assert isinstance(result, ConvertResult)
        assert result.source_type == "docx"
        assert result.title == "report"
        assert "# report" in result.content
        assert "First paragraph" in result.content
        assert "Second paragraph" in result.content

    @pytest.mark.asyncio
    async def test_convert_docx_from_bytes(self):
        """DOCX bytes 输入。"""
        mock_text = "Content from bytes upload"

        with patch(
            "src.collector.converter.office_converter.extract_docx_text",
            return_value=mock_text,
        ):
            result = await self.converter.convert(
                "upload.docx", content=b"fake docx bytes"
            )

        assert result.source_type == "docx"
        assert "Content from bytes" in result.content

    # -- convert XLSX --

    @pytest.mark.asyncio
    async def test_convert_xlsx_with_openpyxl(self):
        """XLSX → Markdown 表格（直接测试 _xlsx_to_markdown_table）。"""
        mock_ws = MagicMock()
        mock_ws.title = "Sheet1"
        mock_ws.iter_rows.return_value = [
            ("Name", "Age", "City"),
            ("Alice", 30, "Beijing"),
            ("Bob", 25, "Shanghai"),
        ]

        mock_wb = MagicMock()
        mock_wb.worksheets = [mock_ws]

        # 直接测试静态方法
        md = OfficeConverter._xlsx_to_markdown_table(mock_wb)
        assert "| Name | Age | City |" in md
        assert "| Alice | 30 | Beijing |" in md
        assert "| Bob | 25 | Shanghai |" in md
        assert "| --- |" in md
        assert "## Sheet1" in md

    @pytest.mark.asyncio
    async def test_convert_xlsx_fallback(self):
        """XLSX 无 openpyxl 时降级到 extract_xlsx_text。"""
        with patch(
            "src.collector.converter.office_converter.extract_xlsx_text",
            return_value="Name\tAge\nAlice\t30",
        ), patch(
            "src.collector.converter.office_converter.OfficeConverter._xlsx_to_markdown_table",
            side_effect=ImportError("no openpyxl"),
        ):
            # 当 _xlsx_to_markdown_table 不可用时，降级到 extract_xlsx_text
            # 但当前实现中 openpyxl 是延迟 import，如果 import 失败就走 extract_xlsx_text
            # 我们直接测试 extract_xlsx_text 被调用的场景
            pass

        # 实际测试：直接调用 extract_xlsx_text
        with patch(
            "src.collector.converter.office_converter.extract_xlsx_text",
            return_value="Name\tAge\nAlice\t30",
        ):
            # 模拟 openpyxl 不可用的情况
            import builtins
            real_import = builtins.__import__
            def mock_import(name, *args, **kwargs):
                if name == "openpyxl":
                    raise ImportError("no openpyxl")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = await self.converter.convert("data.xlsx")

        assert "Name" in result.content
