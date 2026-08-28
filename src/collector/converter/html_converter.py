# ruflo-kb/src/collector/converter/html_converter.py
"""HTML → Markdown 转换器。

复用 utils/text.py 的 html_to_text 和 utils/extract/html.py 的表格转换。
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import ConvertResult, ConverterBase
from ...utils.extract.html import convert_html_tables_to_markdown
from ...utils.text import html_to_text


class HtmlConverter(ConverterBase):
    """HTML → Markdown（文本提取 + 表格转换）。"""

    _EXTS = {".html", ".htm"}

    def can_handle(self, source: str | Path) -> bool:
        return Path(str(source)).suffix.lower() in self._EXTS

    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:
        source_path = Path(str(source))

        # 读取 HTML
        if content is not None:
            html = content.decode("utf-8", errors="replace")
        else:
            html = source_path.read_text(encoding="utf-8", errors="replace")

        # 提取标题
        title = self._extract_html_title(html) or source_path.stem

        # HTML → Markdown
        md = self._html_to_markdown(html, title)

        return ConvertResult(
            content=md,
            title=title,
            metadata={"format": "html", "size": len(html)},
            source_type="html",
            original_path=str(source),
        )

    @staticmethod
    def _extract_html_title(html: str) -> str:
        """从 HTML 提取 <title> 或第一个 <h1>。"""
        # <title> 标签
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()

        # 第一个 <h1>
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()

        return ""

    @staticmethod
    def _html_to_markdown(html: str, title: str) -> str:
        """将 HTML 转换为 Markdown。"""
        # 1. 表格先转 Markdown
        md = convert_html_tables_to_markdown(html)

        # 2. 剩余 HTML 转纯文本
        text = html_to_text(md)

        # 3. 加标题
        if title and not text.strip().startswith(f"# {title}"):
            text = f"# {title}\n\n{text}"

        return text
