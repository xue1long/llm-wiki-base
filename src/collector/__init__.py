# ruflo-kb/src/collector/__init__.py
"""独立采集模块 — 接收任意输入（文件/URL/图片），转换为 Markdown。

与 pipeline/collector.py 的区别：
- 零框架依赖（不依赖 EventBus、permissions、queue）
- 可独立用于脚本、CLI、测试
- 仅依赖 utils/extract/ 的纯函数和 llm/base.py 的抽象接口
"""
from .converter.base import ConvertResult, ConverterBase
from .converter.exceptions import UnsupportedSourceError
from .collector import Collector  # noqa: F401 — Task 7 填充

__all__ = [
    "ConvertResult",
    "ConverterBase",
    "UnsupportedSourceError",
    "Collector",
]
