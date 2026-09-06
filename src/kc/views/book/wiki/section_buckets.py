"""Deterministic section buckets for wiki content blocks."""
from __future__ import annotations

_BUCKETS = {
    "overview": "概述", "summary": "概述", "method": "方法", "pitfall": "陷阱",
    "case": "案例", "reference": "参考", "example": "案例",
}


def bucket_for_heading(heading: str | None) -> str:
    if heading is None or not heading.strip():
        return "前言"
    key = heading.strip().casefold()
    return _BUCKETS.get(key, "未分类")


__all__ = ["bucket_for_heading"]
