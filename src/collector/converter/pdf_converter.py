# ruflo-kb/src/collector/converter/pdf_converter.py
"""PDF → Markdown 转换器。

复用 utils/extract/pdf.py 的纯文本提取，加上结构化 Markdown 格式化。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .base import ConvertResult, ConverterBase
from ...utils.extract.pdf import extract_pdf_text


class PdfConverter(ConverterBase):
    """PDF → 结构化 Markdown。"""

    _EXTS = {".pdf"}

    def can_handle(self, source: str | Path) -> bool:
        return Path(str(source)).suffix.lower() in self._EXTS

    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:

        source_str = str(source)

        # 如果传入的是 bytes（如上传的文件），先写入临时文件
        tmp_path: str | None = None
        if content is not None:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(content)
            tmp.close()
            tmp_path = tmp.name
            source_str = tmp_path

        try:
            text = extract_pdf_text(source_str)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        title = Path(str(source)).stem
        md = self._to_markdown(text, title)

        return ConvertResult(
            content=md,
            title=title,
            metadata={"pages": text.count("<!-- page:")},
            source_type="pdf",
            original_path=str(source),
        )

    @staticmethod
    def _to_markdown(text: str, title: str) -> str:
        """将 PDF 提取的纯文本转换为结构化 Markdown。

        保留 <!-- page: N --> 标注作为分节标记。
        """
        lines = text.split("\n")
        result: list[str] = [f"# {title}", ""]

        for line in lines:
            if line.startswith("<!-- page:"):
                # 提取页码
                try:
                    page_num = line.split(":")[1].strip().rstrip("--> ").strip()
                except (IndexError, ValueError):
                    page_num = "?"
                result.append(f"\n---\n\n## 第 {page_num} 页\n")
            else:
                result.append(line)

        return "\n".join(result)
