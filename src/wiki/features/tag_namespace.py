"""Validate wiki page tags use controlled namespace prefixes."""
from typing import Iterable


TAG_PREFIXES = {
    "genre": "题材类型",
    "func": "功能类型",
    "char": "角色类型",
    "event": "事件类型",
    "mood": "情绪氛围",
    "entity": "是什么 (What)",
    "scene_phase": "何时用 (When)",
    "status": "生命周期",
}


def is_valid(tag: str) -> bool:
    """True if tag uses one of 8 controlled prefixes."""
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
