# ruflo-kb/src/collector/converter/base.py
"""转换器抽象接口 — 所有格式转换器的基类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConvertResult:
    """格式转换结果。

    Attributes:
        content:     转换后的 Markdown 文本
        title:       提取的标题（用于文件命名和页面标题）
        metadata:    额外元数据（页数、作者、格式等）
        source_type: 原始类型标识（pdf / docx / xlsx / html / text / image / url）
        original_path: 原始文件路径或 URL
        raw_bytes:   原始文件字节（图片等需要保留原件时使用）
    """

    content: str
    title: str = ""
    metadata: dict = field(default_factory=dict)
    source_type: str = "text"
    original_path: str = ""
    raw_bytes: bytes | None = None


class ConverterBase(ABC):
    """格式转换器抽象基类。

    每个转换器负责：
    1. 判断是否能处理某个输入源（can_handle）
    2. 将输入源转换为 Markdown（convert）
    """

    @abstractmethod
    def can_handle(self, source: str | Path) -> bool:
        """判断是否能处理该输入源。

        Args:
            source: 文件路径（str 或 Path）或 URL

        Returns:
            True 如果该转换器可以处理此源
        """
        ...

    @abstractmethod
    async def convert(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
    ) -> ConvertResult:
        """将输入源转换为 Markdown。

        Args:
            source:  文件路径或 URL
            content: 可选的文件字节内容（避免重复读取磁盘/网络）

        Returns:
            ConvertResult 包含转换后的 Markdown 和元数据

        Raises:
            转换失败时抛出具体异常（如 EncryptedDocumentError）
        """
        ...
