"""Stage 2 canonical models — Task 3 contract scaffold.

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

Task 3 is the contract scaffold; Task 5 will rewrite
``article_segmenter.py`` to slice source_bytes directly (currently char
offsets are converted to byte offsets in the wrapping layer).
"""
from __future__ import annotations

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


__all__ = [
    "CanonicalItem",
    "CoverageReport",
    "ItemKind",
    "SegmentationResult",
    "SegmentationStatus",
]