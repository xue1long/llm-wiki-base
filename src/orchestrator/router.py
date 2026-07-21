# ruflo-kb/src/orchestrator/router.py
from enum import Enum

class TaskIntent(str, Enum):
    INGEST = "ingest"
    SEARCH = "search"
    UNKNOWN = "unknown"

def route_task(input_text: str) -> TaskIntent:
    """识别任务意图"""
    lower = input_text.lower().strip()

    # 检索模式
    if lower.startswith("?") or lower.startswith("search:") or lower.startswith("find:"):
        return TaskIntent.SEARCH

    # 入库模式
    if lower.startswith("http") or ".md" in lower or ".pdf" in lower or ".doc" in lower:
        return TaskIntent.INGEST

    return TaskIntent.INGEST

def parse_source(input_text: str) -> tuple[str, str]:
    """
    解析来源
    返回 (source, source_type)
    """
    trimmed = input_text.strip()

    if trimmed.startswith("http"):
        return trimmed, "url"

    return trimmed, "file"
