"""Manifest-only cross-link candidates."""
from __future__ import annotations

from typing import Any

_NAMESPACE_RELATIONS = frozenset({
    "taxonomy_of", "belongs_to_audience", "hosted_on_platform", "has_credibility",
})


def build_cross_link_candidates(outline: dict[str, Any], page_ids: set[str] | frozenset[str]) -> list[dict[str, str]]:
    """Keep only candidates whose endpoints are existing, distinct page IDs."""
    result = []
    for item in outline.get("cross_link_candidates", ()) if isinstance(outline, dict) else ():
        if not isinstance(item, dict):
            continue
        source, target, reason = item.get("from_page"), item.get("to_page"), item.get("reason")
        if (all(isinstance(x, str) and x for x in (source, target, reason))
                and source != target and source in page_ids and target in page_ids):
            result.append({"from_page": source, "to_page": target, "reason": reason})
    return result


def validate_cross_links(outline: dict[str, Any], page_ids: set[str] | frozenset[str]) -> dict[str, Any]:
    """Return fail-closed diagnostics for cross-link candidates.

    ``ok`` is True iff no dangling, self-loop, or malformed candidates remain.
    Namespace edges (``taxonomy_of`` / ``belongs_to_audience`` /
    ``hosted_on_platform`` / ``has_credibility``) are excluded from the
    failure ratio, mirroring :func:`aggregator.relation_stats`.
    """
    kept, dangling, self_loops, malformed = [], [], [], []
    namespace_skipped = 0
    for item in outline.get("cross_link_candidates", ()) if isinstance(outline, dict) else ():
        if not isinstance(item, dict):
            malformed.append({"item": str(item)})
            continue
        source, target, reason = item.get("from_page"), item.get("to_page"), item.get("reason")
        if not all(isinstance(x, str) and x for x in (source, target, reason)):
            malformed.append({"from_page": source, "to_page": target, "reason": reason})
            continue
        row = {"from_page": source, "to_page": target, "reason": reason}
        if reason in _NAMESPACE_RELATIONS:
            namespace_skipped += 1
        elif source == target:
            self_loops.append(row)
        elif source not in page_ids or target not in page_ids:
            dangling.append(row)
        else:
            kept.append(row)
    return {"ok": not (dangling or self_loops or malformed), "kept": kept,
            "dangling": dangling, "self_loops": self_loops,
            "malformed": malformed, "namespace_skipped": namespace_skipped}


def find_dangling_cross_links(outline: dict[str, Any],
                              page_ids: set[str] | frozenset[str]) -> list[dict[str, str]]:
    """Return only the dangling cross-link candidates (excluding namespace edges)."""
    return list(validate_cross_links(outline, page_ids)["dangling"])


def dangling_cross_links(outline: dict[str, Any],
                         page_ids: set[str] | frozenset[str]) -> list[dict[str, str]]:
    """Alias for :func:`find_dangling_cross_links`."""
    return find_dangling_cross_links(outline, page_ids)


__all__ = ["build_cross_link_candidates", "validate_cross_links",
           "find_dangling_cross_links", "dangling_cross_links", "_NAMESPACE_RELATIONS"]
