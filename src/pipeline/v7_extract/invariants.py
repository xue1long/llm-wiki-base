"""Stage 2 invariant validator — Task 3 (master plan §3.2 I1–I5).

Five mechanical invariants that every ``SegmentationResult`` must pass
before downstream stages consume ``CanonicalItem.start_byte`` /
``end_byte``. The validator is pure (no I/O, no LLM) and returns an
``InvariantReport`` describing which checks passed.

The invariants are designed to catch the most common byte-offset bugs:

  - I1: at least one item OR status in {UNCERTAIN, FAILED} (master plan §3.2)
  - I2: 0 <= start < end <= source_size
  - I3: items sorted by start_byte
  - I4: items non-overlapping (intersection == 0)
  - I5: byte accounting == source size (sum of spans = source bytes)

Why these five and not more (FP10 master plan §3.2):
  - The contract is byte-anchored: downstream stages (Stage 5
    ``CanonicalSpan``, Stage 7 ``revision_hash``) only need this much
    surface area to stay honest about source offsets.
  - Adding "all items decode cleanly" or "no item is pure whitespace"
    is LLM-domain knowledge and belongs in segmentation.py,
    not invariants.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from .segmentation import CanonicalItem, SegmentationStatus


@dataclass
class InvariantReport:
    """Mechanical invariant check result. ``all_pass`` is True only when
    every individual invariant is True.

    Plan: docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md Task 1
    Added ``i5_gap_at_tail`` and ``i5_gap_bytes`` so callers (Stage 3/7)
    can distinguish natural ASR-style end-of-source gaps from real
    segmentation bugs. ``all_pass`` is unchanged: the two new fields
    are descriptive signals, not part of the strict I1–I5 contract.
    """

    i1_nonempty: bool             # items >= 1 OR status in {UNCERTAIN, FAILED}
    i2_boundaries_valid: bool     # 0 <= start < end <= source_size
    i3_sorted: bool               # sorted by start_byte (stable on ties)
    i4_non_overlapping: bool      # intersection == 0 between all pairs
    i5_complete_accounting: bool   # sum of spans == source bytes
    i5_gap_at_tail: bool = False  # i5 failed AND gap is only at end
    i5_gap_bytes: int = 0         # size of the gap (bytes) when i5 failed

    @property
    def all_pass(self) -> bool:
        return all((
            self.i1_nonempty,
            self.i2_boundaries_valid,
            self.i3_sorted,
            self.i4_non_overlapping,
            self.i5_complete_accounting,
        ))


def validate_segmentation_invariants(
    items: list[CanonicalItem],
    *,
    source_size: int,
    status: SegmentationStatus | None = None,
) -> InvariantReport:
    """Run the five mechanical invariants over ``items``.

    Args:
        items: the partition to validate (may be empty).
        source_size: total bytes of the original source. Must be >= 0.
        status: if provided, I1 is satisfied when status is UNCERTAIN
            or FAILED even with no items. This matches master plan §3.2
            "items >= 1 OR status in {UNCERTAIN, FAILED}".

    Returns:
        InvariantReport with every individual flag set. The caller
        inspects individual flags to decide ``SegmentationStatus``
        (DEGRADED vs FAILED vs SEGMENTED). ``all_pass`` is True only
        when every flag is True. ``i5_gap_at_tail`` / ``i5_gap_bytes``
        describe the gap shape when I5 fails.
    """
    # I1: empty items is OK only when status is UNCERTAIN or FAILED
    if items:
        i1 = True
    elif status in (SegmentationStatus.UNCERTAIN, SegmentationStatus.FAILED):
        i1 = True
    else:
        i1 = False

    # I2: each item must have 0 <= start < end <= source_size
    i2 = all(
        0 <= item.start_byte < item.end_byte <= source_size
        for item in items
    )

    # I3: sorted by start_byte
    i3 = all(
        items[i].start_byte <= items[i + 1].start_byte
        for i in range(len(items) - 1)
    )

    # I4: non-overlapping (item[i].end <= item[i+1].start on sorted input)
    # Empty span already fails I2, so we don't need a special case here.
    i4 = all(
        items[i].end_byte <= items[i + 1].start_byte
        for i in range(len(items) - 1)
    )

    # I5: byte accounting == source size
    #     Sum of all spans equals total source bytes (no gap, no overlap,
    #     no overflow).
    total = sum(item.end_byte - item.start_byte for item in items)
    i5 = (total == source_size) and i4

    # Gap shape: only meaningful when i5 failed and we have items.
    # Tail residue = items cover [0, end_byte_of_last) leaving a final gap.
    # Middle gap = last item ends at source_size but a gap exists before it
    # (i4 would already be False in that case, so i5_gap_at_tail=False).
    i5_gap_at_tail = False
    i5_gap_bytes = 0
    if not i5 and items:
        last_end = items[-1].end_byte
        if last_end < source_size and i4:
            i5_gap_at_tail = True
            i5_gap_bytes = source_size - last_end
        elif last_end == source_size:
            # items[-1] reaches the end but total != source_size means a
            # middle gap exists (or items overlap — handled by i4).
            i5_gap_at_tail = False
            i5_gap_bytes = source_size - total

    return InvariantReport(
        i1_nonempty=i1,
        i2_boundaries_valid=i2,
        i3_sorted=i3,
        i4_non_overlapping=i4,
        i5_complete_accounting=i5,
        i5_gap_at_tail=i5_gap_at_tail,
        i5_gap_bytes=i5_gap_bytes,
    )


__all__ = ["InvariantReport", "validate_segmentation_invariants"]