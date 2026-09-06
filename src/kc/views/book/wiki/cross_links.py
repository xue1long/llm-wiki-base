"""Manifest-only cross-link candidates."""
from __future__ import annotations

from typing import Any


def build_cross_link_candidates(outline: dict[str, Any], page_ids: set[str] | frozenset[str]) -> list[dict[str, str]]:
    """Keep only candidates whose endpoints are existing page IDs."""
    result = []
    for item in outline.get("cross_link_candidates", ()) if isinstance(outline, dict) else ():
        if not isinstance(item, dict):
            continue
        source, target, reason = item.get("from_page"), item.get("to_page"), item.get("reason")
        if all(isinstance(x, str) and x for x in (source, target, reason)) and source in page_ids and target in page_ids:
            result.append({"from_page": source, "to_page": target, "reason": reason})
    return result


__all__ = ["build_cross_link_candidates"]
