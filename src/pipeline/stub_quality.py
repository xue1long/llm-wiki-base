"""C3: Stub quality control — importance scoring, filtering, and reference-list detection.

Provides:
  - StubImportance enum (HIGH, MEDIUM, LOW)
  - Heuristic importance scoring based on wikilink frequency and relation weight
  - filter_low_importance_stubs — split missing slugs into kept vs inlined
  - detect_reference_list_density — ratio of list lines to total lines
"""
from __future__ import annotations

import re
from enum import Enum


class StubImportance(str, Enum):
    """Importance tier for a missing-entity stub."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Characters that identify a line as a list item.
_LIST_LEADING_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")


def detect_reference_list_density(text: str) -> float:
    """Return the ratio of list-item lines to total non-blank lines.

    A "list line" starts with ``-``, ``*``, or a numbered pattern (``1.``,
    ``1)``).  Only non-blank lines are counted so a short doc with a few
    blank lines does not artificially inflate the ratio.

    Returns a float in [0.0, 1.0].  A document is considered "list-heavy"
    when the ratio exceeds 0.6 (60%).
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return 0.0
    list_count = sum(1 for l in lines if _LIST_LEADING_RE.match(l))
    return list_count / len(lines)


def _score_slug_importance(
    slug: str,
    pages_body_text: dict[str, str],
    *,
    wikilink_weight: float = 3.0,
    text_mention_weight: float = 1.0,
    high_threshold: int = 3,
    medium_threshold: int = 1,
) -> StubImportance:
    """Heuristic importance score for a single missing slug.

    A slug is scored by counting:
    - Body wikilink references (``[[slug]]``) — higher weight
    - Plain-text mentions of the slug/title — lower weight

    Parameters
    ----------
    slug: The stub slug being scored.
    pages_body_text: ``{page_id: body_text}`` for all pages in this ingest.
    wikilink_weight: Multiplier for wikilink matches.
    text_mention_weight: Multiplier for plain-text matches.
    high_threshold: Score >= this → HIGH.
    medium_threshold: Score >= this → MEDIUM, otherwise LOW.
    """
    score = 0.0

    # Build a plain-text search variant: replace hyphens with space and CJK
    # characters stay as-is.
    search_text = slug.replace("-", " ")

    for _pid, body in pages_body_text.items():
        if not body:
            continue
        # Count [[wikilink]] references
        wikilinks = re.findall(
            r"\[\[" + re.escape(slug) + r"(?:\|[^\]]*)?\]\]",
            body,
        )
        score += len(wikilinks) * wikilink_weight

        # Count plain-text mentions (case-insensitive for ASCII, exact for CJK)
        if search_text and search_text != slug:
            # Two search patterns: original slug form and space-separated form
            mentions = len(re.findall(re.escape(search_text), body, re.IGNORECASE))
            if mentions == 0:
                mentions = len(re.findall(re.escape(slug), body, re.IGNORECASE))
        else:
            mentions = len(re.findall(re.escape(slug), body, re.IGNORECASE))
        score += mentions * text_mention_weight

    if score >= high_threshold:
        return StubImportance.HIGH
    elif score >= medium_threshold:
        return StubImportance.MEDIUM
    else:
        return StubImportance.LOW


def filter_low_importance_stubs(
    missing_slugs: set[str],
    pages: list,
) -> dict[str, StubImportance]:
    """Score each missing slug and return ``{slug: importance}``.

    Slugs scored as LOW should be inlined as ``related_entities`` on the
    source page rather than creating stub entity pages.  HIGH and MEDIUM
    slugs should proceed to stub creation.

    Parameters
    ----------
    missing_slugs: Slugs referenced by pages but not yet existing.
    pages: Generated WikiPage objects (have ``.id`` and ``.body`` attributes).
    """
    # Build {page_id: body} lookup from the generated pages
    pages_body: dict[str, str] = {}
    for p in pages:
        pid = getattr(p, "id", "")
        body = getattr(p, "body", "")
        if pid:
            pages_body[pid] = body

    result: dict[str, StubImportance] = {}
    for slug in missing_slugs:
        result[slug] = _score_slug_importance(slug, pages_body)
    return result


def split_by_importance(
    scored: dict[str, StubImportance],
) -> tuple[set[str], set[str]]:
    """Split scored slugs into (kept, inlined).

    *kept* — HIGH and MEDIUM slugs that should become stub pages.
    *inlined* — LOW slugs that should become ``related_entities`` on the
    source page.
    """
    kept: set[str] = set()
    inlined: set[str] = set()
    for slug, imp in scored.items():
        if imp == StubImportance.LOW:
            inlined.add(slug)
        else:
            kept.add(slug)
    return kept, inlined


def sort_stubs_by_importance(
    slugs: set[str],
    scored: dict[str, StubImportance],
) -> list[str]:
    """Return *slugs* sorted by importance (HIGH first, then MEDIUM, then LOW)."""
    order = {StubImportance.HIGH: 0, StubImportance.MEDIUM: 1, StubImportance.LOW: 2}
    return sorted(slugs, key=lambda s: order.get(scored.get(s, StubImportance.LOW), 2))
