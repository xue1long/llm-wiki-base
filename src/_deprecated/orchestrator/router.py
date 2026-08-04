# ruflo-kb/src/orchestrator/router.py
from enum import Enum
from pathlib import PurePosixPath


class TaskIntent(str, Enum):
    INGEST = "ingest"
    SEARCH = "search"


# Extensions that strongly imply the user wants to ingest a document.
# Suffix-based: we look at the trailing token of the input, not substring
# matches anywhere in it. This prevents natural-language questions like
# "what is the .md format?" from being mis-classified as INGEST.
_INGEST_SUFFIXES = frozenset({".md", ".pdf", ".docx", ".doc", ".txt"})


def route_task(input_text: str) -> TaskIntent:
    """识别任务意图

    Routing rules:
      * Empty / whitespace-only input raises ``ValueError`` (callers should
        never dispatch an empty task).
      * Inputs containing ``?`` (anywhere), or starting with ``search:`` /
        ``find:`` are SEARCH. ``?`` covers natural-language questions like
        "what is the .md format?".
      * Inputs starting with ``http(s)://`` are INGEST.
      * Inputs whose final whitespace-separated token ends in one of the
        known document extensions are INGEST.
      * Anything else is INGEST (default; matches prior behaviour for
        plain text / path inputs).
    """
    if not input_text or not input_text.strip():
        raise ValueError("route_task: empty input")

    lower = input_text.lower().strip()

    # 检索模式 — explicit prefixes
    if lower.startswith("?") or lower.startswith("search:") or lower.startswith("find:"):
        return TaskIntent.SEARCH

    # Any '?' anywhere in the input signals a natural-language question.
    # Covers inputs like "what is the .md format?" that contain a
    # document-extension token but are still questions.
    if "?" in lower:
        return TaskIntent.SEARCH

    # 入库模式
    if lower.startswith("http"):
        return TaskIntent.INGEST

    # Suffix match on the trailing whitespace-separated token.
    # Use PurePosixPath so the lookup is pure-string (no filesystem access).
    trimmed = input_text.strip()
    last_token = trimmed.split()[-1] if trimmed.split() else ""
    try:
        suffix = PurePosixPath(last_token).suffix.lower()
    except ValueError:
        suffix = ""
    if suffix in _INGEST_SUFFIXES:
        return TaskIntent.INGEST

    # Default: treat as ingest (preserves legacy behaviour for plain paths
    # and natural-language phrases that the operator wants to ingest).
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
