"""Optional evidence-bound cross-page index for encyclopedic builds.

The provider sees only a small allow-listed summary.  Its output is treated as
untrusted data and is rejected unless every evidence locator exists in the
snapshot.
"""
from __future__ import annotations

import json
import re
from typing import Any


class EncyclopedicUnavailable(RuntimeError):
    """The optional provider path cannot produce a usable index."""


_PII = re.compile(r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)\d[\d ()+.-]{6,}\d(?!\d)|(?:sk|api|key)[_-]?[A-Za-z0-9]{12,})", re.I)


def _safe_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text or _PII.search(text):
        return ""
    return text[:500]


def _evidence(snapshot: Any) -> set[tuple[str, str]]:
    return {(b.page_id, b.block_id) for p in snapshot.pages for b in p.content_blocks}


def safe_summary(snapshot: Any) -> list[dict[str, Any]]:
    """Return the fixed outbound allow-list; bodies and source paths excluded."""
    return [{"page_id": p.page_id, "title": p.title, "taxonomy": p.primary_taxonomy,
             "summary": _safe_summary(p.summary), "block_ids": [b.block_id for b in p.content_blocks]}
            for p in snapshot.pages]


def _pairs(value: Any, valid: set[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise EncyclopedicUnavailable("evidence must be a list")
    result = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("page_id"), str) or not isinstance(item.get("block_id"), str):
            raise EncyclopedicUnavailable("evidence locator is malformed")
        pair = (item["page_id"], item["block_id"])
        if pair not in valid:
            raise EncyclopedicUnavailable(f"unknown evidence locator: {pair[0]}:{pair[1]}")
        result.append(pair)
    if not result:
        raise EncyclopedicUnavailable("evidence is required")
    return tuple(result)


def validate_outline(payload: Any, snapshot: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EncyclopedicUnavailable("outline must be an object")
    valid = _evidence(snapshot)
    issues = payload.get("issues", [])
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise EncyclopedicUnavailable("issues must be non-empty strings")
    consensus = []
    for item in payload.get("consensus", []):
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str):
            raise EncyclopedicUnavailable("consensus claim is malformed")
        consensus.append({"claim": item["claim"], "evidence": [list(x) for x in _pairs(item.get("evidence"), valid)]})
    disagreement = []
    for item in payload.get("disagreement", []):
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str):
            raise EncyclopedicUnavailable("disagreement claim is malformed")
        disagreement.append({"claim": item["claim"],
                             "supporting_evidence": [list(x) for x in _pairs(item.get("supporting_evidence"), valid)],
                             "contradicting_evidence": [list(x) for x in _pairs(item.get("contradicting_evidence"), valid)]})
    cross_links = []
    page_ids = {p.page_id for p in snapshot.pages}
    for item in payload.get("cross_link_candidates", []):
        if not isinstance(item, dict):
            raise EncyclopedicUnavailable("cross-link candidate is malformed")
        source, target, reason = item.get("from_page"), item.get("to_page"), item.get("reason")
        if not all(isinstance(x, str) and x.strip() for x in (source, target, reason)):
            raise EncyclopedicUnavailable("cross-link candidate is malformed")
        if source not in page_ids or target not in page_ids:
            raise EncyclopedicUnavailable("cross-link candidate references unknown page")
        cross_links.append({"from_page": source, "to_page": target, "reason": reason})
    return {"issues": issues, "consensus": consensus, "disagreement": disagreement,
            "cross_link_candidates": cross_links}


async def generate_encyclopedic_outline(snapshot: Any, provider: Any) -> dict[str, Any]:
    """Generate and validate the optional index; provider failure is explicit."""
    if provider is None or not callable(getattr(provider, "complete", None)):
        raise EncyclopedicUnavailable("LLM provider unavailable")
    prompt = json.dumps({"task": "Return JSON issues/consensus/disagreement with evidence page_id and block_id.",
                         "pages": safe_summary(snapshot)}, ensure_ascii=False)
    try:
        response = await provider.complete([{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        content = getattr(response, "content", getattr(response, "text", ""))
        if getattr(response, "truncated", False) or not isinstance(content, str) or not content.strip():
            raise EncyclopedicUnavailable("LLM response unavailable or truncated")
        return validate_outline(json.loads(content), snapshot)
    except EncyclopedicUnavailable:
        raise
    except Exception as exc:
        raise EncyclopedicUnavailable(f"LLM provider unavailable: {exc}") from exc


__all__ = ["EncyclopedicUnavailable", "safe_summary", "validate_outline", "generate_encyclopedic_outline"]
