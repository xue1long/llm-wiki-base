"""Validate wiki page tags use controlled namespace prefixes."""
from typing import Iterable


TAG_PREFIXES = {
    "题材": "题材类型",
    "功能": "功能类型",
    "角色": "角色类型",
    "事件": "事件类型",
    "情绪": "情绪氛围",
    "实体": "是什么 (What)",
    "场景阶段": "何时用 (When)",
    "状态": "生命周期",
    "素材": "素材品类",
    "可信度": "可信度",
}


def is_valid(tag: str) -> bool:
    """True if tag uses one of 10 controlled prefixes."""
    return any(tag.startswith(prefix + "/") for prefix in TAG_PREFIXES)


def parse(tag: str) -> tuple[str, str] | None:
    """Returns (prefix, name) or None if invalid."""
    if "/" not in tag:
        return None
    prefix, _, name = tag.partition("/")
    if prefix in TAG_PREFIXES:
        return prefix, name
    return None


def validate_tags(tags: Iterable[str]) -> list[str]:
    """Return list of invalid tags (must be empty for valid tag set)."""
    return [t for t in tags if not is_valid(t)]
