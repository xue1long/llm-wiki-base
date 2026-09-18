"""Stage 2 canonical models + deterministic splitter — Task 3 / Task 4.

This module defines the Stage 2 contract that downstream stages consume
(Stage 3, Stage 5, Stage 7 — see master plan §2.2 cross-stage shared
variables). The contract replaces the legacy ``list[dict[str, str]]``
shape with explicit, validated types.

Coordinate system (master plan §3.2 + Task 5):
  - ``CanonicalItem.start_byte`` / ``end_byte`` are **UTF-8 byte offsets**
    against the original source bytes (not character offsets).
  - ``CanonicalItem.text`` is the decoded substring at ``[start_byte:end_byte]``.
  - Stage 5 ``CanonicalSpan.start_byte`` is **item-relative** offset
    (``source_offset = item.start_byte + span.start_byte``).

The deterministic splitter ``extract_items_deterministic`` (moved from
``scripts/extract_pilot.py`` in V7 replace Plan Stage 0 Task 1) lets
the V7 ingest bridge reuse the same offline-heuristic Stage 2 path
that the dry-run pilot uses — without crossing the scripts/ module
boundary. Task 5 will rewrite ``article_segmenter.py`` to slice
``source_bytes`` directly, at which point the byte offsets produced
here will be authoritative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .invariants import InvariantReport


class SegmentationStatus(str, Enum):
    """Stage 2 outcome (master plan §3.5).

    Maps to ExtractionStatus five-state in the caller via stage-local
    enum → ExtractionStatus mapping (not direct assignment).
    """

    SEGMENTED = "segmented"           # multi-item partition with full coverage
    SINGLE_EXPECTED = "single_expected"  # 结构证据表明就是一篇
    DEGRADED = "degraded"             # 有切分但 residual/uncertainty 高
    UNCERTAIN = "uncertain"           # 无法可靠定边界
    FAILED = "failed"                  # 技术失败或 invariant 破坏


class ItemKind(str, Enum):
    """Per-item classification."""

    ARTICLE = "article"
    SECTION = "section"
    LIST_ITEM = "list_item"
    RESIDUAL = "residual"
    BOILERPLATE = "boilerplate"
    UNKNOWN = "unknown"


@dataclass
class CanonicalItem:
    """One segmented item from the source (master plan §3.2 L1).

    Byte coordinates are **UTF-8 byte offsets against the original source
    bytes** — not Python character indices. To slice the source text:
    ``source_bytes[item.start_byte:item.end_byte].decode("utf-8")``.
    """

    item_id: str
    kind: ItemKind
    start_byte: int            # UTF-8 byte offset, inclusive
    end_byte: int              # UTF-8 byte offset, exclusive
    title: str | None
    text: str                  # decoded at item creation; matches the byte span
    boundary_sources: list[str] = field(default_factory=list)
    confidence: float = 1.0
    display_index: int = 0     # render-only index (sort/iterate order)


@dataclass
class CoverageReport:
    """How much of the source the segmentation accounts for."""

    byte_accounting: float        # sum(item spans) / source bytes; 1.0 = full
    structured_coverage: float    # bytes covered by ARTICLE items / source bytes
    residual_ratio: float         # bytes in RESIDUAL items / source bytes
    unknown_ratio: float          # bytes in UNKNOWN items / source bytes


@dataclass
class SegmentationResult:
    """Stage 2 output contract. Every field is required (no None)."""

    status: SegmentationStatus
    method: str                   # "structural_deterministic" | "llm_window" | "fallback_single"
    items: list[CanonicalItem]
    coverage: CoverageReport
    invariants: InvariantReport
    warnings: list[str]
    structural_signals: dict      # header_count / byline_count / qa_marker_count / ...
    source_hash: str              # hash of original source bytes (sha1[:16])
    segmenter_fingerprint: str    # pipe-<16hex> per Contract 4.4
    residual_items: list[CanonicalItem]   # convenience view of kind=RESIDUAL items


# ---------------------------------------------------------------------------
# Deterministic Stage 2 splitter (moved from scripts/extract_pilot.py in
# V7 replace Plan Stage 0 Task 1 so the V7 ingest bridge can reuse it).
# ---------------------------------------------------------------------------

# STRICT form (canonical, shared with doc_classifier._AUTHOR_BYLINE_RE):
#   ``作者 : XXX`` or ``作者：XXX`` — used for evidence_summary accounting.
# HEADING form (used by actual novel-wiki fixtures):
#   ``## 作者 314 — 如何更好地包装作品`` — heading-wrapped bylines.
# Both forms are accepted by the splitter; the strict count is the
# Stage 1 evidence_summary signal, the broad match is the Stage 2 split.
AUTHOR_BYLINE_RE_STRICT = re.compile(r"(?m)^\s*作者\s*[:：]\s*\S{1,20}\s*$")
AUTHOR_BYLINE_RE_BROAD = re.compile(
    r"(?m)^(?:\s*#+\s+)?\s*作者\s*[:：]?\s*\S{1,20}\s*(?:—|-|：|:|$)",
)


def _extract_items_by_author_byline(
    content: str, relative: str,
) -> list[dict[str, str]]:
    """Split a source on ``作者 XXX`` byline lines.

    Each item's ``text`` runs from the byline line up to (but not
    including) the next byline line — never overlapping, always sorted
    by source position. Returns an empty list when the content has no
    bylines; the caller decides whether to fall through to other
    splitters based on the count.

    Accepts both the strict ``作者 : XXX`` form (doc_classifier
    evidence_summary signal) and the heading-wrapped
    ``## 作者 314 — Title`` form found in actual fixtures.
    """
    matches = list(AUTHOR_BYLINE_RE_BROAD.finditer(content))
    if not matches:
        return []
    items: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[match.start():end].strip()
        items.append({
            "id": f"{relative}#author-{index + 1}",
            "text": text,
        })
    return items


def extract_items_deterministic(content: str, relative: str) -> list[dict[str, str]]:
    """Deterministic structural splitter — Task 4 contract.

    Tries structural splitters in order of decreasing specificity:
      1. Author byline (``作者 XXX``) — strongest signal for
         multi-author collections (master plan Task 4). Used even when
         Stage 1 mis-classifies the source as ``multi_section``; Stage 2
         no longer reads ``doc_type`` for this decision.
      2. ``## `` markdown headings — existing v2 fallback.
      3. Numbered list — existing v2 fallback for short listicles.
      4. Single-item fallback — wraps the whole content as one item.

    Each splitter is pure (no LLM call, no doc_type input) so the path
    stays deterministic and bounded (Contract 3 §3.4: Stage 2 must not
    feed full ``content`` to an LLM; this is the offline-heuristic
    branch that runs before the LLM window resolver wired in Task 5).
    """
    byline_items = _extract_items_by_author_byline(content, relative)
    if len(byline_items) >= 2:
        return byline_items
    headings = list(re.finditer(r"(?m)^#{1,3}\s+(.+?)\s*$", content))
    if len(headings) >= 2:
        items = []
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            text = content[match.start():end].strip()
            items.append({"id": f"{relative}#section-{index + 1}", "text": text})
        return items
    numbered = [line.strip() for line in content.splitlines() if re.match(r"^\d+[.、,，)]\s*\S", line)]
    if len(numbered) >= 3:
        return [
            {"id": f"{relative}#item-{index + 1}", "text": text}
            for index, text in enumerate(numbered)
        ]
    return [{"id": relative, "text": content.strip()}]


def wrap_items_as_segmentation_result(
    items: list[dict[str, str]],
    *,
    content: str,
    source_md5: str,
    relative: str,
) -> SegmentationResult:
    """Task 3 contract scaffold: wrap the legacy ``list[dict]`` shape
    into a ``SegmentationResult``.

    The downstream Stage 4 still consumes ``items`` (the dict list) —
    this wrapper is informational. Task 5 will rewrite
    ``article_segmenter.py`` to slice source_bytes directly, at which
    point the byte offsets produced here will be authoritative.

    Coordinate conversion (char offset -> UTF-8 byte offset) is
    mechanical: ``len(content[:char_start].encode("utf-8"))``. The
    position is found by searching ``item["text"]`` in ``content``;
    a fresh ``char`` scan yields the char start of the substring.
    """
    source_bytes = content.encode("utf-8")
    source_size = len(source_bytes)
    canonical_items: list[CanonicalItem] = []
    warnings: list[str] = []
    # Track char cursor so we can slice items in source order.
    char_cursor = 0
    boundary_sources = ["metadata_header", "byline", "llm_window", "fallback"]

    for index, raw in enumerate(items):
        text = raw.get("text") or ""
        if not text:
            warnings.append(f"item_{index}_empty_text")
            canonical_items.append(CanonicalItem(
                item_id=str(raw.get("id") or f"{relative}#item-{index}"),
                kind=ItemKind.UNKNOWN,
                start_byte=0,
                end_byte=0,
                title=raw.get("title"),
                text="",
                boundary_sources=boundary_sources,
                confidence=0.0,
                display_index=index,
            ))
            continue
        # Locate the text in the content starting from cursor (avoids the
        # ``.find`` ambiguity when items share substrings).
        char_start = content.find(text, char_cursor)
        if char_start < 0:
            # Last resort: scan from offset 0. Records a degraded item so
            # invariant I4/I5 can surface the gap.
            char_start = content.find(text)
            warnings.append(f"item_{index}_text_out_of_order")
        if char_start < 0:
            warnings.append(f"item_{index}_text_not_located")
            canonical_items.append(CanonicalItem(
                item_id=str(raw.get("id") or f"{relative}#item-{index}"),
                kind=ItemKind.UNKNOWN,
                start_byte=0,
                end_byte=0,
                title=raw.get("title"),
                text="",
                boundary_sources=boundary_sources,
                confidence=0.0,
                display_index=index,
            ))
            continue
        start_byte = len(content[:char_start].encode("utf-8"))
        end_byte = start_byte + len(text.encode("utf-8"))
        canonical_items.append(CanonicalItem(
            item_id=str(raw.get("id") or f"{relative}#item-{index}"),
            kind=ItemKind.ARTICLE,
            start_byte=start_byte,
            end_byte=end_byte,
            title=raw.get("title"),
            text=text,
            boundary_sources=boundary_sources,
            confidence=1.0,
            display_index=index,
        ))
        char_cursor = char_start + len(text)

    # Imported lazily to avoid an import cycle (invariants depends on
    # segmentation CanonicalItem/SegmentationStatus).
    from .invariants import validate_segmentation_invariants

    invariants = validate_segmentation_invariants(
        canonical_items, source_size=source_size,
    )

    # Decide SegmentationStatus from invariants + coverage
    if invariants.all_pass:
        if len(canonical_items) == 1:
            status = SegmentationStatus.SINGLE_EXPECTED
        else:
            status = SegmentationStatus.SEGMENTED
    elif invariants.i1_nonempty and not invariants.i5_complete_accounting:
        status = SegmentationStatus.DEGRADED
    elif not invariants.i1_nonempty:
        status = SegmentationStatus.UNCERTAIN
    else:
        # invariant broken but I1 still satisfied -> invariant validation
        # failed -> FAILED (technical contract violation, per Failure
        # Contract 1).
        status = SegmentationStatus.FAILED

    article_bytes = sum(
        ci.end_byte - ci.start_byte
        for ci in canonical_items
        if ci.kind == ItemKind.ARTICLE
    )
    coverage = CoverageReport(
        byte_accounting=sum(
            ci.end_byte - ci.start_byte for ci in canonical_items
        ) / source_size if source_size else 0.0,
        structured_coverage=article_bytes / source_size if source_size else 0.0,
        residual_ratio=0.0,
        unknown_ratio=sum(
            (ci.end_byte - ci.start_byte) for ci in canonical_items
            if ci.kind == ItemKind.UNKNOWN
        ) / source_size if source_size else 0.0,
    )
    return SegmentationResult(
        status=status,
        method="structural_deterministic",
        items=canonical_items,
        coverage=coverage,
        invariants=invariants,
        warnings=warnings,
        structural_signals={"item_count": len(canonical_items)},
        source_hash=source_md5,
        segmenter_fingerprint="seg-fp-task3",
        residual_items=[],
    )


def build_structural_summary(
    segmentation_result: SegmentationResult,
    *,
    content: str,
) -> dict:
    """Task 7: produce the bounded structural summary Stage 3 consumes.

    Per master plan Task 7 / Contract Freeze §3.2 — Stage 3's evidence
    pack embeds Stage 2 signals so the LLM can judge completeness from
    structural cues (item count / kind distribution / boundary
    confidence / last-item truncation flag) instead of guessing from
    raw text. The dict is JSON-serializable; values are short scalars
    so the embedded signal text in the bounded pack stays small.
    """
    items = segmentation_result.items
    article_count = sum(1 for it in items if it.kind == ItemKind.ARTICLE)
    section_count = sum(1 for it in items if it.kind == ItemKind.SECTION)
    source_bytes = len(content.encode("utf-8"))
    last_item_truncated = bool(items) and items[-1].end_byte > source_bytes
    return {
        "item_count": len(items),
        "article_count": article_count,
        "section_count": section_count,
        "status": segmentation_result.status.value,
        "boundary_confidence": (
            1.0 if segmentation_result.invariants.all_pass else 0.5
        ),
        "byte_accounting": round(segmentation_result.coverage.byte_accounting, 4),
        "last_item_truncated": last_item_truncated,
    }


__all__ = [
    "AUTHOR_BYLINE_RE_BROAD",
    "AUTHOR_BYLINE_RE_STRICT",
    "CanonicalItem",
    "CoverageReport",
    "ItemKind",
    "SegmentationResult",
    "SegmentationStatus",
    "_extract_items_by_author_byline",
    "build_structural_summary",
    "extract_items_deterministic",
    "wrap_items_as_segmentation_result",
]