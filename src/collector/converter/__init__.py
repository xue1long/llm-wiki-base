# ruflo-kb/src/collector/converter/__init__.py
"""格式转换器子包 — 各格式 → Markdown 的转换器。"""
from .base import ConvertResult, ConverterBase
from .exceptions import UnsupportedSourceError

__all__ = [
    "ConvertResult",
    "ConverterBase",
    "UnsupportedSourceError",
]
