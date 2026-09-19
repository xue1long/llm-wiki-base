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
    MAX_TAIL_GAP_BYTES,
    SegmentationResult,
    SegmentationStatus,
    build_structural_summary,
    wrap_items_as_segmentation_result,
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


# ---------------------------------------------------------------------------
# Plan 2026-09-17 / Task 5: UTF-8 byte offset coordinate system.
#
# The LLM segmenter currently stores ``start`` / ``end`` as if they were
# byte offsets, but the prompt is fed the decoded ``text`` (char) and the
# LLM effectively returns char offsets. On Chinese content the mismatch
# silently breaks slicing — Python ``str[a:b]`` indexes by char, but
# every CJK char is 3 UTF-8 bytes, so a "byte" pointer in the middle of
# a multi-byte char lands on the wrong boundary.
#
# F5 (master plan §6) is the hard rule: ``test_chinese_byte_offset_slice_consistent``
# must pass before Stage 5 can consume Stage 2 byte spans.
# ---------------------------------------------------------------------------

import warnings

from src.pipeline.v7_extract.article_segmenter import (
    ArticleBoundary,
    _payload_to_boundaries,
)


def _chinese_fixture() -> tuple[str, bytes]:
    """Return a Chinese source string + its UTF-8 bytes.

    Layout (chars):
        "前言\\n\\n" + "作者 314 — 如何更好地包装作品\\n\\n" + "正文一。" * 5
        + "作者 阿零 — 解决卡文的三两招\\n\\n" + "正文二。" * 5

    Why this fixture exposes the bug:
        - "知" / "识" / "前" / "言" are 3 UTF-8 bytes each
        - 11 ASCII chars ("作者 314 — " prefix) are 1 byte each
        - char offsets differ from byte offsets by exactly 2*3 = 6 bytes
          once we cross the first CJK char
    """
    text = (
        "前言\n\n"
        "作者 314 — 如何更好地包装作品\n\n"
        + "正文一。" * 5
        + "\n\n"
        + "作者 阿零 — 解决卡文的三两招\n\n"
        + "正文二。" * 5
    )
    return text, text.encode("utf-8")


def test_byte_offset_against_utf8_source_bytes() -> None:
    """ArticleBoundary carries char offsets against the original source
    text. ``slice_bytes(source_bytes)`` must convert char→byte and slice
    raw bytes; ``slice_text(source_bytes)`` must return the decoded
    substring.

    This is the contract that downstream Stage 5 relies on when it
    receives ``CanonicalItem.start_byte/end_byte`` (which is the same
    coordinate system, just applied to the source bytes).
    """
    text, source_bytes = _chinese_fixture()
    # char offsets into the source text (the LLM returns these because
    # the prompt input was the decoded ``text``).
    boundary = ArticleBoundary(
        char_start=0,
        char_end=len("前言\n\n作者 314 — 如何更好地包装作品\n\n正文一。正文一。正文一。"),
        title="作者 314 — 如何更好地包装作品",
    )

    # slice_text decodes correctly even though char_start/char_end are
    # not byte offsets — the conversion is mechanical.
    sliced = boundary.slice_text(source_bytes)
    assert sliced == text[boundary.char_start:boundary.char_end]
    # And the bytes are exactly the UTF-8 encoding of those chars.
    assert boundary.slice_bytes(source_bytes) == sliced.encode("utf-8")


def test_chinese_string_byte_offset_consistent() -> None:
    """F5 — char slice through UTF-8 source MUST equal byte slice through
    the same char range. This is the hard invariant for Stage 5 byte
    spans: a char-range slice must produce the exact bytes that would
    round-trip through .encode()/.decode().

    Concretely: pick a char range that crosses a CJK char boundary,
    take ``text[char_start:char_end]`` and
    ``source_bytes.decode("utf-8")[char_start:char_end]`` — both must
    agree AND must be valid UTF-8 when re-encoded.
    """
    text, source_bytes = _chinese_fixture()
    # Pick a range starting mid-CJK to make the bug visible: start at
    # char 1 (inside "前言") so char/byte offsets diverge by 2 bytes.
    char_start = 1
    char_end = len("前言\n\n作者 314 — 如何更好地包装作品\n\n正文一。正文一。")
    boundary = ArticleBoundary(char_start=char_start, char_end=char_end, title="")

    # Honest char indexing (Python str)
    expected_text = text[char_start:char_end]
    # What slice_text returns when we hand it the source bytes
    got_text = boundary.slice_text(source_bytes)

    assert got_text == expected_text
    # The byte count of the slice must equal the byte count of the
    # char-sliced result — this is what proves the conversion is honest
    # (a buggy implementation would return e.g. 6 fewer bytes because
    # it sliced source_bytes with char_start, hitting the middle of a
    # 3-byte CJK char and re-encoding garbage).
    assert len(got_text.encode("utf-8")) == len(expected_text.encode("utf-8"))
    # And round-trip: re-encoding then re-decoding yields the same text.
    assert got_text.encode("utf-8").decode("utf-8") == got_text


def test_chinese_byte_offset_slice_consistent() -> None:
    """F5 硬指标 — the exact hard metric from the master plan.

    The bug scenario: suppose someone (legacy code, an old caller, a
    future Stage 5 mistake) hands raw byte offsets to ``slice_text``
    instead of char offsets. The conversion must STILL be correct: a
    char-anchored slice through the bytes yields the same text as a
    char slice through the source string.

    The fixture is positioned so that char 0 == byte 0, but char N
    (for N > 2) differs from byte N by exactly ``2 * 3 = 6`` bytes
    (because each of "前" / "言" is 3 UTF-8 bytes). Any naive byte
    arithmetic that ignores this would slice to the wrong position.
    """
    text, source_bytes = _chinese_fixture()
    # Pick a range that crosses both the "前言" 2-char/6-byte region
    # AND the "作者 314 — " ASCII region, so byte offset ≠ char offset
    # in BOTH directions (CJK shrinks byte offset, ASCII preserves it).
    char_start = len("前言\n\n")
    char_end = char_start + len("作者 314 — 如何更好地包装作品\n\n正文一。正文一。")
    boundary = ArticleBoundary(char_start=char_start, char_end=char_end, title="")

    expected = text[char_start:char_end]
    got = boundary.slice_text(source_bytes)

    assert got == expected
    # The bug signature: if slice_text indexed source_bytes with
    # char_start (treating it as byte offset), it would slice from byte
    # char_start — which is mid-CJK in this fixture — and
    # ``.decode("utf-8")`` would either crash (decode raises) or
    # produce garbled text. The current implementation must NOT do
    # that.
    assert got.encode("utf-8")[:6] == "正文一。".encode("utf-8")[:6] or got.startswith("作者 314")
    # Strong invariant: the decoded text must be valid UTF-8 round-trip.
    assert got.encode("utf-8").decode("utf-8") == got


def test_article_boundary_slice_bytes_returns_correct_text() -> None:
    """``slice_bytes`` returns the raw UTF-8 bytes corresponding to the
    char range. The bytes, when decoded, must match the char-slice
    result.

    This is the wire-format contract that Stage 5 ``CanonicalSpan``
    consumers (and any future downstream byte-exact tooling) rely on.
    """
    text, source_bytes = _chinese_fixture()
    boundary = ArticleBoundary(
        char_start=0,
        char_end=len(text),
        title="whole doc",
    )

    raw = boundary.slice_bytes(source_bytes)
    assert raw == source_bytes  # whole-doc slice == whole source
    assert raw.decode("utf-8") == text

    # A sub-range: must be exactly the UTF-8 encoding of the char slice
    char_start = len("前言\n\n")
    char_end = char_start + len("作者 314 — 如何更好地包装作品\n\n")
    boundary2 = ArticleBoundary(char_start=char_start, char_end=char_end, title="")
    sub = boundary2.slice_bytes(source_bytes)
    assert sub.decode("utf-8") == text[char_start:char_end]
    # Round-trip: the bytes must decode to valid UTF-8 of the right
    # length (char count, not byte count).
    assert len(sub.decode("utf-8")) == char_end - char_start


def test_article_boundary_legacy_slice_emits_deprecation_warning() -> None:
    """The legacy ``ArticleBoundary.slice(content)`` API assumed
    char-indexed slicing. Now that ``start`` / ``end`` have been renamed
    to ``char_start`` / ``char_end`` and the canonical API is
    ``slice_bytes`` / ``slice_text``, the legacy method emits a
    ``DeprecationWarning`` so existing callers can migrate.

    The method must STILL work (callers shouldn't crash) — it just
    warns once per call. After the warning, it must produce the same
    text as ``slice_text``.
    """
    text, source_bytes = _chinese_fixture()
    boundary = ArticleBoundary(
        char_start=0,
        char_end=len("前言\n\n作者 314 — 如何更好地包装作品\n\n"),
        title="",
    )

    with pytest.warns(DeprecationWarning, match="byte offset"):
        legacy = boundary.slice(text)
    # Legacy still produces the correct substring (for backward compat).
    assert legacy == boundary.slice_text(source_bytes)


def test_payload_to_boundaries_uses_char_offsets_for_chinese() -> None:
    """Task 5 acceptance: ``_payload_to_boundaries`` must use char
    offsets (not byte offsets) when normalizing LLM output. On Chinese
    content, the LLM returns offsets measured against the decoded
    ``text`` (the prompt input) — those are char offsets. If the
    helper naively stored them as bytes, slicing would corrupt CJK
    boundaries.

    The test fixture has char/byte offset divergence of exactly 6
    bytes (two 3-byte CJK chars at the start). A buggy implementation
    that stored char offsets as bytes would return boundaries whose
    ``char_start`` > ``char_end`` or that point into the middle of a
    CJK char (visible as a mismatched ``title`` location).
    """
    text, _source_bytes = _chinese_fixture()
    payload = {
        "articles": [
            {
                "start": 0,
                "end": len("前言\n\n作者 314 — 如何更好地包装作品\n\n正文一。正文一。"),
                "title": "作者 314 — 如何更好地包装作品",
            },
            {
                "start": len("前言\n\n作者 314 — 如何更好地包装作品\n\n正文一。正文一。"),
                "end": len(text),
                "title": "作者 阿零 — 解决卡文的三两招",
            },
        ]
    }

    boundaries = _payload_to_boundaries(payload, text)
    assert len(boundaries) == 2
    # The first boundary must start at char 0 (which happens to equal
    # byte 0 here — the bug would shift it by 6 if it stored byte
    # offsets in a char field).
    first = boundaries[0]
    assert first.char_start == 0
    # The substring at [char_start:char_end] must contain the title text.
    assert "作者 314" in text[first.char_start:first.char_end]
    second = boundaries[1]
    assert "作者 阿零" in text[second.char_start:second.char_end]
    # Adjacency: end[0] == start[1] (LLM contract)
    assert first.char_end == second.char_start


# ---------------------------------------------------------------------------
# TAIL_RESIDUE classification — Plan: 2026-09-19-v7-stage2-i5-lineage-unblock Task 1
#
# ASR transcripts commonly leave a few bytes at end-of-source after
# deterministic splitting (trailing punctuation / ASR error chars).
# I5 fails (strict byte accounting), but the gap is only at the tail
# — not a real segmentation bug. Classify as TAIL_RESIDUE so Stage 3
# sees boundary_confidence=1.0 instead of the degraded 0.5 signal.
# ---------------------------------------------------------------------------

# Constants from the plan: 1024 bytes is the empirical ASR-tail-gate.
MAX_TAIL_GAP_BYTES = 1024


def _make_result_with_tail_gap(
    *, gap_bytes: int, source_size: int = 200,
) -> SegmentationResult:
    """Build a SegmentationResult where items cover everything except the
    final ``gap_bytes`` bytes of the source. Mirrors what real
    deterministic splitting produces on ASR transcripts.

    ``source_size`` defaults to 200; tests for threshold boundaries
    (1024, 1025 bytes) pass a larger value.
    """
    span = source_size - gap_bytes
    items = [
        _make_item(
            item_id="a", start_byte=0, end_byte=span,
            text="x" * span,
        ),
    ]
    invariants = validate_segmentation_invariants(items, source_size=source_size)
    coverage = CoverageReport(
        byte_accounting=span / source_size,
        structured_coverage=1.0,
        residual_ratio=0.0,
        unknown_ratio=0.0,
    )
    return SegmentationResult(
        status=SegmentationStatus.DEGRADED,  # placeholder — overwritten by caller
        method="structural_deterministic",
        items=items,
        coverage=coverage,
        invariants=invariants,
        warnings=[],
        structural_signals={"item_count": len(items)},
        source_hash="",
        segmenter_fingerprint="seg-fp-test",
        residual_items=[],
    )


def test_build_structural_summary_sets_boundary_confidence_1_for_tail_residue():
    """When SegmentationStatus is TAIL_RESIDUE, boundary_confidence must
    be 1.0 — not 0.5. This is the structural signal Stage 3 LLM reads."""
    result = _make_result_with_tail_gap(gap_bytes=10)
    # Manually upgrade status to TAIL_RESIDUE (the wrapper under test is
    # build_structural_summary, which only consumes status).
    object.__setattr__(result, "status", SegmentationStatus.TAIL_RESIDUE)
    summary = build_structural_summary(result, content="x" * 200)
    assert summary["status"] == "tail_residue"
    assert summary["boundary_confidence"] == 1.0
    assert summary["byte_accounting"] < 1.0  # byte accounting 真实反映 gap


def test_build_structural_summary_keeps_half_confidence_for_degraded():
    """DEGRADED status (middle gap / big tail gap) keeps boundary_confidence=0.5.
    TAIL_RESIDUE only upgrades the tail-end small-gap case."""
    result = _make_result_with_tail_gap(gap_bytes=10)
    object.__setattr__(result, "status", SegmentationStatus.DEGRADED)
    summary = build_structural_summary(result, content="x" * 200)
    assert summary["boundary_confidence"] == 0.5


def test_build_structural_summary_half_confidence_for_failed_status():
    """FAILED status (real segmentation bug) keeps boundary_confidence=0.5."""
    result = _make_result_with_tail_gap(gap_bytes=10)
    object.__setattr__(result, "status", SegmentationStatus.FAILED)
    summary = build_structural_summary(result, content="x" * 200)
    assert summary["boundary_confidence"] == 0.5


def _segment_with_exact_tail_gap(gap_bytes: int) -> SegmentationResult:
    """Drive ``wrap_items_as_segmentation_result`` with a source whose
    deterministic partition covers everything but the final ``gap_bytes``
    bytes. ``content.find(text, cursor)`` locates the single item, so the
    gap size is exact. This exercises the real status decision — not a
    placeholder status assignment.
    """
    item_text = "A" * 100
    trailing = "B" * gap_bytes
    content = item_text + trailing
    return wrap_items_as_segmentation_result(
        [{"id": "a", "text": item_text}],
        content=content,
        source_md5="md5",
        relative="x.md",
    )


def test_tail_residue_threshold_boundary_1024_includes_exact():
    """A tail gap of exactly MAX_TAIL_GAP_BYTES (1024) classifies as
    TAIL_RESIDUE — the threshold is inclusive (``<=``, not ``<``).
    Spec: plan 2026-09-19-v7-stage2-i5-lineage-unblock §Task 1 Round 1 ③-C.
    """
    result = _segment_with_exact_tail_gap(MAX_TAIL_GAP_BYTES)
    assert result.invariants.i5_complete_accounting is False  # I5 strictly fails
    assert result.invariants.i5_gap_at_tail is True
    assert result.invariants.i5_gap_bytes == MAX_TAIL_GAP_BYTES
    assert result.status is SegmentationStatus.TAIL_RESIDUE
    summary = build_structural_summary(
        result, content="A" * 100 + "B" * MAX_TAIL_GAP_BYTES,
    )
    assert summary["boundary_confidence"] == 1.0


def test_tail_residue_threshold_boundary_1025_degrades():
    """One byte over the threshold (1025) must NOT get the TAIL_RESIDUE
    exemption — it degrades to DEGRADED with boundary_confidence 0.5, so
    Stage 3 still sees the original "something is off" signal. This is the
    off-by-one guard the spec asked for (plan §Task 1 Round 1 ③-C).
    """
    result = _segment_with_exact_tail_gap(MAX_TAIL_GAP_BYTES + 1)
    assert result.invariants.i5_complete_accounting is False
    assert result.invariants.i5_gap_at_tail is True
    assert result.invariants.i5_gap_bytes == MAX_TAIL_GAP_BYTES + 1
    assert result.status is SegmentationStatus.DEGRADED
    summary = build_structural_summary(
        result, content="A" * 100 + "B" * (MAX_TAIL_GAP_BYTES + 1),
    )
    assert summary["boundary_confidence"] == 0.5


def test_build_structural_summary_half_confidence_for_uncertain_failed():
    """UNCERTAIN / FAILED statuses (downstream reads) keep half_confidence."""
    result = _make_result_with_tail_gap(gap_bytes=10)
    for status in (SegmentationStatus.UNCERTAIN, SegmentationStatus.FAILED):
        object.__setattr__(result, "status", status)
        summary = build_structural_summary(result, content="x" * 200)
        assert summary["boundary_confidence"] == 0.5, (
            f"{status.value} must keep 0.5 confidence"
        )