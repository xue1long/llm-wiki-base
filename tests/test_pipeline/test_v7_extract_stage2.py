"""Tests for Task 3 — Stage 2 SegmentationResult + InvariantReport contract.

The contract is the foundation for downstream stages (Stage 3 / Stage 5 / Stage 7
consume CanonicalItem.start_byte/end_byte). The five mechanical invariants
defined in master plan §3.2 are validated here.

Task 4 tests live at the bottom of this file: they verify Stage 2's
structural signal independence from Stage 1 ``doc_type`` (Bounded Evidence
Contract §3.4 + Failure Contract §1).
"""
from __future__ import annotations

import pytest

from scripts.extract_pilot import (
    _extract_items,
    _extract_items_by_author_byline,
    _looks_like_collection,
)
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


# ---------------------------------------------------------------------------
# Plan 2026-09-17 / Task 4: Stage 2 must not depend on Stage 1's
# ``doc_type == "collection"`` to detect a multi-author collection. The
# structural signal is computed locally from the content itself
# (author bylines / metadata headers) and Stage 2 still segments even
# when Stage 1 mis-classifies the document.
#
# Bounded Evidence Contract §3.4 — candidate window resolver (LLM) is
# Task 5's responsibility; Task 4 only adds deterministic structural
# splitters that do not depend on Stage 1's doc_type.
# ---------------------------------------------------------------------------


_COLLECTION_FIXTURE = (
    "# 前言\n\n这是一篇介绍性前言。\n\n"
    "## 作者 314 — 如何更好地包装作品\n\n包装作品的具体方法。\n\n"
    "## 作者 阿零 — 解决卡文的三两招\n\n卡文的应对策略。\n\n"
    "## 作者 ZENK — 写在新人成功之前\n\n新人心态调整。\n"
)


_SINGLE_DOC_FIXTURE = (
    "# 单一文章标题\n\n这是一篇很长的单一文章。\n\n" + ("正文段落。" * 200)
)


def test_author_byline_deterministic_split_works_without_collection_doc_type() -> None:
    """Task 4: ``_extract_items_by_author_byline`` finds author byline
    boundaries regardless of Stage 1 classification.

    The fixture has 3 author byline lines (``作者 314``, ``作者 阿零``,
    ``作者 ZENK``). The splitter must return exactly 3 items, one per
    author — no LLM call, no Stage 1 doc_type gate, no overlap.
    """
    items = _extract_items_by_author_byline(_COLLECTION_FIXTURE, "raw/sources/collection.md")

    assert len(items) == 3
    # Each item must carry the full byline + body for the author
    assert "作者 314" in items[0]["text"]
    assert "作者 阿零" in items[1]["text"]
    assert "作者 ZENK" in items[2]["text"]
    # No overlap — each item's text contains its byline marker at the
    # very top (allowing for an optional ``#`` / ``##`` heading prefix
    # that the broad regex tolerates).
    for index, marker in enumerate(("作者 314", "作者 阿零", "作者 ZENK")):
        # Strip leading whitespace + optional ``#`` heading markers, then
        # confirm the byline marker is the first non-heading token.
        head = items[index]["text"]
        assert marker in head.split("\n", 1)[0], (
            f"item {index} first line should contain {marker!r}; got "
            f"{head.split(chr(10))[0]!r}"
        )
    # Stable per-source ids — namespace is ``<relative>#author-N``
    assert items[0]["id"].endswith("#author-1")
    assert items[1]["id"].endswith("#author-2")
    assert items[2]["id"].endswith("#author-3")


def test_stage2_runs_even_when_doc_type_wrong() -> None:
    """Task 4 acceptance: Stage 1 mis-classifies the source as
    ``multi_section`` but the content is actually a multi-author
    collection. Stage 2's deterministic splitter must still split by
    author bylines — proving structural signal independence.

    We simulate the wrong doc_type by feeding the collection fixture
    through ``_extract_items`` directly: Stage 2's structural path must
    NOT consult any doc_type argument; the helper signature stays the
    same as before (content, relative).
    """
    items = _extract_items(_COLLECTION_FIXTURE, "raw/sources/collection.md")

    # The collection fixture has 3 author bylines but the doc_type hint
    # is unknown to _extract_items (the helper no longer reads
    # doc_type). The splitter must find 3 byline-bounded items — not
    # the 1-section fallback and not the regex-heading fallback
    # (which only matches `## ` headings, not byline lines).
    assert len(items) >= 3, (
        f"expected at least 3 items (one per author), got {len(items)}; "
        "Stage 2 is still consulting doc_type instead of structural signals"
    )
    # All three authors must appear across the resulting items
    flat_text = "\n".join(item["text"] for item in items)
    for author in ("314", "阿零", "ZENK"):
        assert author in flat_text, f"author {author!r} lost in segmentation"


def test_first_match_wins_replaced_with_strong_weak_invalid_classification() -> None:
    """Task 4: ``_looks_like_collection`` is a SOFT structural hint
    derived from the content itself — never a hard gate. The function
    must be pure (no Stage 1 coupling), cheap (single regex sweep), and
    monotonic in the structural evidence:

      - 0 author bylines + 0 metadata headers → False
      - ≥ 1 author bylines + ≥ 1 metadata header → True (collection-like)

    This protects the Stage 1 doc_type contract: even when Stage 1
    returns ``failed=True`` (LLM outage) the structural hint stays
    computable from the raw content.
    """
    # No structural evidence at all — single coherent article
    assert _looks_like_collection(_SINGLE_DOC_FIXTURE) is False
    # ≥ 2 author bylines AND ≥ 1 metadata header (the "前言" H1)
    assert _looks_like_collection(_COLLECTION_FIXTURE) is True
    # Edge case: a single byline + no metadata header is NOT collection
    assert _looks_like_collection(
        "## 作者 314 — 单一文章\n\n正文。"
    ) is False