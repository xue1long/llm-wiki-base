# ruflo-kb/src/collector/collector.py
"""顶层编排器 — 接收输入 → 选择转换器 → 转换 → 写入 raw/sources/。

独立于 pipeline/collector.py，不依赖 EventBus、permissions、queue。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .converter.base import ConvertResult, ConverterBase
from .converter.exceptions import UnsupportedSourceError
from .converter.pdf_converter import PdfConverter
from .converter.office_converter import OfficeConverter
from .converter.html_converter import HtmlConverter
from .converter.text_converter import TextConverter
from .converter.image_converter import ImageConverter
from .converter.url_converter import UrlConverter
from .writer.raw_writer import write_to_raw

logger = logging.getLogger(__name__)


class Collector:
    """独立采集器 — 接收任意输入，转换为 Markdown，写入 raw/sources/。

    使用::

        collector = Collector(project_root=Path("/path/to/project"), llm_provider=provider)
        result = await collector.collect("paper.pdf")
        result = await collector.collect("https://example.com/article")
        result = await collector.collect("screenshot.png")
        result = await collector.collect("upload.pdf", content=pdf_bytes)
    """

    def __init__(self, project_root: Path, llm_provider=None):
        self.project_root = Path(project_root)
        self.llm_provider = llm_provider
        self._converters = self._build_converter_chain()

    def _build_converter_chain(self) -> list[ConverterBase]:
        """构建转换器链（按优先级排列）。"""
        return [
            UrlConverter(self.llm_provider),     # URL → 抓取 + 转换
            ImageConverter(self.llm_provider),   # 图片 → Markdown（LLM Vision）
            PdfConverter(),                      # PDF → Markdown
            OfficeConverter(),                   # DOCX/XLSX → Markdown
            HtmlConverter(),                     # HTML → Markdown
            TextConverter(),                     # TXT/MD → 直通
        ]

    def _find_converter(self, source: str | Path) -> ConverterBase | None:
        """找到能处理该源的转换器。"""
        for converter in self._converters:
            if converter.can_handle(source):
                return converter
        return None

    async def collect(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
        filename: str | None = None,
    ) -> ConvertResult:
        """主入口：接收任意输入，转换为 Markdown，写入 raw/sources/。

        Args:
            source:   文件路径或 URL
            content:  可选的文件字节内容（避免重复读取磁盘/网络）
            filename: 可选的输出文件名覆盖

        Returns:
            ConvertResult 包含转换后的 Markdown 和元数据

        Raises:
            UnsupportedSourceError: 没有转换器能处理该输入
        """
        converter = self._find_converter(source)
        if converter is None:
            raise UnsupportedSourceError(str(source))

        logger.info("[collector] %s → %s", source, type(converter).__name__)

        # 转换
        result = await converter.convert(source, content=content)

        # 写入 raw/sources/
        raw_path = write_to_raw(result, self.project_root, filename=filename)
        result.original_path = raw_path

        logger.info("[collector] → %s (%s)", raw_path, result.source_type)
        return result
