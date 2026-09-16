"""Tests for Task 3 — Stage 2 SegmentationResult + InvariantReport contract.

The contract is the foundation for downstream stages (Stage 3 / Stage 5 / Stage 7
consume CanonicalItem.start_byte/end_byte). The five mechanical invariants
defined in master plan §3.2 are validated here.
"""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.invariants import (
    InvariantReport,
    validate_segmentation_invariants,
)
from src.pipeline.v7_extract.segmentation import (
    CanonicalItem,
    CoverageReport,
    ItemKind,
    SegmentationResult,
    SegmentationStatus,
)


def _make_item(
    *,
    item_id: str,
    start_byte: int,
    end_byte: int,
    text: str,
    kind: ItemKind = ItemKind.ARTICLE,
) -> CanonicalItem:
    return CanonicalItem(
        item_id=item_id,
        kind=kind,
        start_byte=start_byte,
        end_byte=end_byte,
        title=None,
        text=text,
        boundary_sources=["test"],
        confidence=1.0,
    )


def test_segmentationresult_carries_coverage_and_invariants() -> None:
    """SegmentationResult carries CoverageReport and InvariantReport;
    the basic invariants pass for a well-formed two-item partition."""
    source_text = "alpha content goes here. beta content goes here."
    source_bytes = source_text.encode("utf-8")
    a = _make_item(
        item_id="a", start_byte=0, end_byte=len("alpha content goes here."),
        text="alpha content goes here.",
    )
    b = _make_item(
        item_id="b",
        start_byte=len("alpha content goes here."),
        end_byte=len(source_text),
        text="beta content goes here.",
    )

    invariants = validate_segmentation_invariants([a, b], source_size=len(source_bytes))
    coverage = CoverageReport(
        byte_accounting=1.0,
        structured_coverage=1.0,
        residual_ratio=0.0,
        unknown_ratio=0.0,
    )
    result = SegmentationResult(
        status=SegmentationStatus.SEGMENTED,
        method="structural_deterministic",
        items=[a, b],
        coverage=coverage,
        invariants=invariants,
        warnings=[],
        structural_signals={"header_count": 2},
        source_hash="abc123",
        segmenter_fingerprint="seg-fp-001",
        residual_items=[],
    )

    assert result.coverage.byte_accounting == 1.0
    assert result.coverage.structured_coverage == 1.0
    assert result.invariants.all_pass is True
    assert result.invariants.i1_nonempty is True
    assert result.invariants.i2_boundaries_valid is True
    assert result.invariants.i3_sorted is True
    assert result.invariants.i4_non_overlapping is True
    assert result.invariants.i5_complete_accounting is True
    # residual is a separate accessor — must mirror coverage invariant
    assert result.residual_items == []


def test_invariant_validator_rejects_overlapping_spans() -> None:
    """Invariant I4 (non-overlapping) catches items that share bytes."""
    a = _make_item(item_id="a", start_byte=0, end_byte=10, text="0123456789")
    b = _make_item(item_id="b", start_byte=5, end_byte=15, text="5678901234")

    report = validate_segmentation_invariants([a, b], source_size=20)

    assert report.i4_non_overlapping is False
    assert report.all_pass is False
    # The other four invariants should still pass (overlap is isolated)
    assert report.i1_nonempty is True
    assert report.i2_boundaries_valid is True
    assert report.i3_sorted is True
    assert report.i5_complete_accounting is False  # overlap ⇒ accounting off too


def test_invariant_validator_rejects_uncovered_gaps() -> None:
    """Invariant I5 (complete accounting) catches items that don't span the source."""
    # Items cover bytes [0,10] but source is 20 bytes → 10 byte gap
    a = _make_item(item_id="a", start_byte=0, end_byte=10, text="0123456789")
    b = _make_item(item_id="b", start_byte=10, end_byte=10, text="")  # zero-width

    report = validate_segmentation_invariants([a, b], source_size=20)

    assert report.i5_complete_accounting is False
    assert report.all_pass is False
    # I2 flags the zero-width item (start == end ⇒ empty span)
    assert report.i2_boundaries_valid is False
    # Sorted? Yes
    assert report.i3_sorted is True
    # Non-overlapping? Yes (zero-width touches a)
    assert report.i4_non_overlapping is True


def test_single_expected_status_for_truly_single_doc() -> None:
    """A document with no detectable internal boundaries must report
    SegmentationStatus.SINGLE_EXPECTED — the structural signal is "this is
    one article" rather than "we couldn't find boundaries"."""
    source_bytes = b"a single coherent document with no detectable breaks."
    item = _make_item(
        item_id="whole",
        start_byte=0,
        end_byte=len(source_bytes),
        text=source_bytes.decode("utf-8"),
    )

    invariants = validate_segmentation_invariants([item], source_size=len(source_bytes))
    result = SegmentationResult(
        status=SegmentationStatus.SINGLE_EXPECTED,
        method="fallback_single",
        items=[item],
        coverage=CoverageReport(
            byte_accounting=1.0, structured_coverage=0.0,
            residual_ratio=0.0, unknown_ratio=0.0,
        ),
        invariants=invariants,
        warnings=[],
        structural_signals={"boundary_count": 0},
        source_hash="single-doc",
        segmenter_fingerprint="seg-fp-single",
        residual_items=[],
    )

    assert result.status == SegmentationStatus.SINGLE_EXPECTED
    assert result.invariants.all_pass is True
    assert result.invariants.i1_nonempty is True  # one item is enough
    # The single-item shape passes I5 because it covers 100% of source
    assert result.invariants.i5_complete_accounting is True


def test_uncertain_status_for_ambiguous_structure() -> None:
    """When boundaries cannot be confidently determined, status = UNCERTAIN
    and items may be empty (I1 permits this via the UNCERTAIN carve-out).
    This satisfies the master plan §3.2 invariant I1: items >= 1 OR
    status in {UNCERTAIN, FAILED}."""
    source_bytes = b"unparseable structure: nothing matches."

    invariants = validate_segmentation_invariants(
        [], source_size=len(source_bytes), status=SegmentationStatus.UNCERTAIN,
    )
    result = SegmentationResult(
        status=SegmentationStatus.UNCERTAIN,
        method="structural_deterministic",
        items=[],
        coverage=CoverageReport(
            byte_accounting=0.0, structured_coverage=0.0,
            residual_ratio=0.0, unknown_ratio=1.0,
        ),
        invariants=invariants,
        warnings=["no structural signals matched any pattern"],
        structural_signals={},
        source_hash="ambiguous",
        segmenter_fingerprint="seg-fp-amb",
        residual_items=[],
    )

    assert result.status == SegmentationStatus.UNCERTAIN
    # I1 must accept empty items when status is UNCERTAIN
    assert result.invariants.i1_nonempty is True
    # But other invariants still need to report honestly:
    assert result.invariants.i3_sorted is True  # vacuously true on empty
    assert result.invariants.i4_non_overlapping is True  # vacuously true
    # And the validator still surfaces the byte-accounting gap
    assert result.invariants.i5_complete_accounting is False