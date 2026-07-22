"""Wiki — Obsidian-compatible typed page model + lifecycle.

This package implements the plan `2026-07-22-wiki-v2.md` (Wiki v2.0 Core).
Subpackages and modules are added incrementally.
"""
from .types import (
    PageType, EventName, TaskStatus,
    WikiPage, KnowledgeTask, ReviewItem, make_review_item,
)
from .paths import WikiPaths
from .ensure import ensure_knowledge_base


__all__ = [
    "PageType", "EventName", "TaskStatus",
    "WikiPage", "KnowledgeTask", "ReviewItem", "make_review_item",
    "WikiPaths", "ensure_knowledge_base",
]
