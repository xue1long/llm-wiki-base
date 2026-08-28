# ruflo-kb/src/collector/converter/text_converter.py
"""TXT / MD → Markdown 转换器。

纯文本文件直通，MD 文件原样保留。均提取第一行作为标题。
"""
from __future__ import annotations

from pathlib import Path

from .base import ConvertResult, ConverterBase


class TextConverter(ConverterBase):
    """TXT / MD → Markdown（直通 + 标题提取）。"""

    _EXTS = {".txt", ".md", ".markdown", ".text"}

    def can_handle(self, source: str | Path) -> bool:
        return Path(str(source)).suffix.lower() in self._EXTS

    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:
        source_path = Path(str(source))
        ext = source_path.suffix.lower()

        # 读取内容
        if content is not None:
            text = content.decode("utf-8", errors="replace")
        else:
            text = source_path.read_text(encoding="utf-8", errors="replace")

        # 提取标题
        title = self._extract_title(text) or source_path.stem

        # MD 文件原样返回；TXT 文件加标题头
        if ext == ".md" or ext == ".markdown":
            md = text
        else:
            md = f"# {title}\n\n{text}"

        return ConvertResult(
            content=md,
            title=title,
            metadata={"format": ext.lstrip("."), "size": len(text)},
            source_type="text" if ext == ".txt" else "md",
            original_path=str(source),
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        """从文本中提取标题。

        优先级：
        1. Markdown # 标题（第一行）
        2. TXT 第一行非空文本（截断到 120 字符）
        """
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Markdown 标题
            if line.startswith("# "):
                return line[2:].strip()
            # 第一行非空文本
            return line[:120]
        return ""
