"""Rule-based wiki page quality gate — zero LLM cost.

Three rules catch common LLM output defects:
- PREFIX_GHOST: page id/title starts with ``concept-`` / ``entity-`` etc.
- EMPTY_BODY: body is effectively empty after stripping wikilinks.
- INTRA_BATCH_DUPE: two pages in the same batch have identical body.
"""
import hashlib
import re
from dataclasses import dataclass

from ..wiki.core.types import PageType, WikiPage

_KNOWN_TYPE_PREFIXES = tuple(f"{pt.value}-" for pt in PageType)
_WIKILINK_RE = re.compile(r'\[\[.*?\]\]')


@dataclass
class QualityGateResult:
    pages: list[WikiPage]       # filtered page list (duplicates removed)
    degraded: dict[str, str]    # page_id -> degradation reason


def _has_type_prefix(text: str) -> bool:
    for pfx in _KNOWN_TYPE_PREFIXES:
        if text.lower().startswith(pfx):
            return True
    return False


def _meaningful_length(body: str) -> int:
    """Character count after stripping wikilinks."""
    stripped = _WIKILINK_RE.sub('', body)
    stripped = stripped.replace('-', ' ')  # unordered-list bullets → space
    return len(stripped.strip())


def check_pages(pages: list[WikiPage]) -> QualityGateResult:
    degraded: dict[str, str] = {}
    kept: list[WikiPage] = []

    # Single pass: INTRA_BATCH_DUPE + PREFIX_GHOST + EMPTY_BODY.
    # Duplicate = same body md5.  The first page encountered is kept.
    # LLM output order is arbitrary, but within-batch duplicates have
    # identical body so the choice is immaterial.
    seen_hashes: dict[str, str] = {}  # md5 -> page_id
    for page in pages:
        # --- INTRA_BATCH_DUPE ---
        body = page.body or ""
        h = hashlib.md5(body.encode("utf-8")).hexdigest()
        if h in seen_hashes and page.processing_depth != "stub" and seen_hashes[h] != page.id:
            degraded[page.id] = f"duplicate of {seen_hashes[h]}"
            continue
        if page.processing_depth != "stub":
            seen_hashes[h] = page.id

        # --- PREFIX_GHOST + EMPTY_BODY ---
        reasons: list[str] = []

        if _has_type_prefix(page.id) or _has_type_prefix(page.title):
            page.grade = "C"
            reasons.append(f"prefix_ghost: {page.title}")

        if page.processing_depth != "stub" and page.body is not None:
            if _meaningful_length(page.body) < 20:
                if not reasons:
                    page.grade = "C"
                reasons.append("empty_body")

        if reasons:
            degraded[page.id] = "; ".join(reasons)

        kept.append(page)

    return QualityGateResult(pages=kept, degraded=degraded)
