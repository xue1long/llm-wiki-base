# ruflo-kb/src/collector/converter/image_converter.py
"""图片 → Markdown 转换器。

调用 LLM Vision API 提取图片中的文字并描述图片内容。
无 LLM 时降级为元数据提取。
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from .base import ConvertResult, ConverterBase

logger = logging.getLogger(__name__)

# 支持的图片格式
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# MIME 类型映射
_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

# Vision 提示词
_VISION_PROMPT = (
    "请仔细阅读这张图片，提取其中的所有文字内容，并描述图片的主要内容。\n"
    "如果图片包含表格，请用 Markdown 表格格式输出。\n"
    "如果图片是图表/示意图，请描述其结构和关键信息。\n"
    "输出格式：\n"
    "## 图片内容\n\n[提取的文字]\n\n## 图片描述\n\n[描述]"
)


class ImageConverter(ConverterBase):
    """图片 → Markdown，调用 LLM Vision API。"""

    def __init__(self, llm_provider=None):
        self.llm_provider = llm_provider

    def can_handle(self, source: str | Path) -> bool:
        return Path(str(source)).suffix.lower() in IMAGE_EXTS

    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:
        source_path = Path(str(source))
        ext = source_path.suffix.lower()

        # 读取图片字节
        if content is not None:
            img_bytes = content
        else:
            img_bytes = source_path.read_bytes()

        title = source_path.stem
        img_b64 = base64.b64encode(img_bytes).decode()
        mime = _MIME_MAP.get(ext, "image/png")

        # 尝试 LLM Vision
        if self.llm_provider is not None:
            try:
                md = await self._call_vision(img_b64, mime, title)
                return ConvertResult(
                    content=md,
                    title=title,
                    metadata={
                        "format": ext.lstrip("."),
                        "ocr_method": "llm_vision",
                        "size": len(img_bytes),
                    },
                    source_type="image",
                    original_path=str(source),
                    raw_bytes=img_bytes,
                )
            except Exception as e:
                logger.warning("Vision API failed for %s: %s; falling back to metadata", source, e)

        # 降级：仅元数据
        md = self._fallback_markdown(title, ext, len(img_bytes))
        return ConvertResult(
            content=md,
            title=title,
            metadata={
                "format": ext.lstrip("."),
                "ocr_method": "fallback",
                "size": len(img_bytes),
            },
            source_type="image",
            original_path=str(source),
            raw_bytes=img_bytes,
        )

    async def _call_vision(self, img_b64: str, mime: str, title: str) -> str:
        """调用 LLM Vision API。"""
        response = await self.llm_provider.complete(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{img_b64}"
                    }}
                ]
            }]
        )
        return f"# {title}\n\n{response.content}"

    @staticmethod
    def _fallback_markdown(title: str, ext: str, size: int) -> str:
        """无 LLM 时的降级 Markdown。"""
        size_kb = size / 1024
        return (
            f"# {title}\n\n"
            f"> ⚠️ 未配置 LLM Vision API，无法提取图片内容。\n\n"
            f"## 图片信息\n\n"
            f"- 格式: {ext.lstrip('.')}\n"
            f"- 大小: {size_kb:.1f} KB\n"
            f"- 文件名: {title}{ext}\n\n"
            f"## 手动描述\n\n"
            f"(请在此处添加图片描述)"
        )
