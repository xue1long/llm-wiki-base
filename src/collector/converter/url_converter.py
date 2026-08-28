# ruflo-kb/src/collector/converter/url_converter.py
"""URL → Markdown 转换器。

抓取 URL 内容，根据 Content-Type 分派到对应的转换器。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .base import ConvertResult, ConverterBase

logger = logging.getLogger(__name__)

# URL scheme 检查
_URL_SCHEMES = ("http://", "https://")


class UrlConverter(ConverterBase):
    """URL → Markdown，抓取网页内容并转换。"""

    def __init__(self, llm_provider=None):
        self.llm_provider = llm_provider

    def can_handle(self, source: str | Path) -> bool:
        s = str(source).strip().lower()
        return any(s.startswith(scheme) for scheme in _URL_SCHEMES)

    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:
        import httpx

        url = str(source).strip()

        # 如果已经有 content（如测试传入），直接处理
        if content is not None:
            return await self._dispatch(url, content, "application/octet-stream")

        # 抓取
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ruflo-kb/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        return await self._dispatch(url, resp.content, content_type)

    async def _dispatch(
        self,
        url: str,
        raw_bytes: bytes,
        content_type: str,
    ) -> ConvertResult:
        """根据 Content-Type 分派到对应转换器。"""
        ct = content_type.lower()

        # PDF 链接
        if "pdf" in ct:
            from .pdf_converter import PdfConverter
            return await PdfConverter().convert(url, content=raw_bytes)

        # 图片链接
        if any(t in ct for t in ("image/png", "image/jpeg", "image/webp", "image/gif")):
            from .image_converter import ImageConverter
            return await ImageConverter(self.llm_provider).convert(url, content=raw_bytes)

        # HTML（默认）
        return self._html_to_markdown(url, raw_bytes)

    @staticmethod
    def _html_to_markdown(url: str, raw_bytes: bytes) -> ConvertResult:
        """HTML → Markdown。"""
        from ...utils.extract.html import convert_html_tables_to_markdown
        from ...utils.text import html_to_text

        html = raw_bytes.decode("utf-8", errors="replace")

        # 提取标题
        title = UrlConverter._extract_title(html) or url

        # 表格转换
        md_html = convert_html_tables_to_markdown(html)

        # HTML → 文本
        text = html_to_text(md_html)

        # 加标题
        if not text.strip().startswith(f"# {title}"):
            text = f"# {title}\n\n{text}"

        return ConvertResult(
            content=text,
            title=title,
            metadata={"url": url, "content_type": "html", "size": len(raw_bytes)},
            source_type="url",
            original_path=url,
        )

    @staticmethod
    def _extract_title(html: str) -> str:
        """从 HTML 提取 <title>。"""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()

        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()

        return ""
