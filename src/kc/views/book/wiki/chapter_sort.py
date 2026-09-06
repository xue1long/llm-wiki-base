"""Deterministic chapter page ordering (the single V4 sorting entry point)."""
from __future__ import annotations

from .aggregator import order_pages_within_chapter
from .model import PageRecord


def sort_chapter_pages(chapter: dict, pages: dict[str, PageRecord]) -> tuple[str, ...]:
    return order_pages_within_chapter(chapter, pages, mode="rule_only")


__all__ = ["sort_chapter_pages"]
