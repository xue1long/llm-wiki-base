# ruflo-kb/src/collector/converter/exceptions.py
"""采集模块的异常类型。"""


class UnsupportedSourceError(ValueError):
    """没有转换器能处理该输入源。

    Attributes:
        source: 无法处理的输入源（文件路径或 URL）
    """

    def __init__(self, source: str, message: str = ""):
        self.source = source
        super().__init__(message or f"Unsupported source: {source}")
