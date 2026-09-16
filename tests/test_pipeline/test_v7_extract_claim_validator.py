"""Task 16: script-owned mechanical validation of claims (10 invariants).

The LLM never decides whether its own evidence is valid. Every claim that a
topic produces is re-checked by the script against the canonical items it
cited: ``validate_claim`` emits stable violation-code *prefixes* (the text
before the first ``:``), so callers and tests match on the prefix while the
suffix carries the useful detail.

``EvidenceRef.start_byte`` / ``end_byte`` are SOURCE-ABSOLUTE UTF-8 byte
offsets, so every fixture below builds ``CanonicalItem`` byte bounds and
``EvidenceRef`` ranges in the same coordinate system (CJK text = 3 bytes per
character — see ``test_v7_extract_claim.py`` for the same convention).
"""
from __future__ import annotations

from src.pipeline.v7_extract.claim import (
    Claim,
    ClaimRisk,
    ClaimSupport,
    EvidenceRef,
)
from src.pipeline.v7_extract.claim_validator import (
    MAX_EVIDENCE_BYTES,
    MIN_EVIDENCE_BYTES,
    filter_substantive_claims,
    validate_claim,
)
from src.pipeline.v7_extract.segmentation import CanonicalItem, ItemKind
from src.pipeline.v7_extract.topic_clusterer import OTHER_TOPIC_ID

TOPIC_ID = "topic-1"

# 24 CJK characters -> 72 UTF-8 bytes: comfortably inside 30..3000.
ITEM_TEXT = "扩句法通过增加动作、环境和感官细节，让句子更具体。"
ITEM_START_BYTE = 100
ITEM_END_BYTE = ITEM_START_BYTE + len(ITEM_TEXT.encode("utf-8"))


def _make_item(
    *,
    item_id: str = "item-1",
    text: str = ITEM_TEXT,
    start_byte: int = ITEM_START_BYTE,
) -> CanonicalItem:
    """A real ``CanonicalItem`` whose byte span matches its decoded text."""
    return CanonicalItem(
        item_id=item_id,
        kind=ItemKind.ARTICLE,
        start_byte=start_byte,
        end_byte=start_byte + len(text.encode("utf-8")),
        title="扩句法",
        text=text,
        boundary_sources=["heading"],
        confidence=0.9,
    )


def _ref(
    start_byte: int,
    end_byte: int,
    *,
    item_id: str = "item-1",
    item_index: int = 0,
    span_index: int = 0,
) -> EvidenceRef:
    return EvidenceRef(
        item_id=item_id,
        item_index=item_index,
        span_index=span_index,
        start_byte=start_byte,
        end_byte=end_byte,
    )


def _claim(
    *refs: EvidenceRef,
    claim_id: str = "claim-1",
    text: str = "扩句法让句子更具体。",
    support: ClaimSupport = ClaimSupport.SUPPORTED,
    risk: ClaimRisk = ClaimRisk.LOW,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        slot_name="definition",
        text=text,
        evidence_refs=list(refs),
        support=support,
        confidence=0.8,
        risk=risk,
    )


def _codes(report) -> list[str]:
    """Violation code prefixes — the stable part before the first colon."""
    return [v.split(":", 1)[0] for v in report.violations]


def test_valid_claim_passes_all_invariants() -> None:
    """A well-formed claim over a real CanonicalItem: span inside the item,
    of sane length, in this topic, cited once -> no violations at all."""
    item = _make_item()
    claim = _claim(_ref(item.start_byte, item.end_byte))

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.claim_id == "claim-1"
    assert report.is_valid is True
    assert report.violations == []
    # LOW risk: mechanically valid, so the expensive semantic reviewer
    # (Task 17) is not worth invoking.
    assert report.needs_reviewer is False
    # The ref really does point at the item's text (coordinate sanity).
    assert claim.evidence_refs[0].end_byte - claim.evidence_refs[0].start_byte == len(
        ITEM_TEXT.encode("utf-8")
    )


def test_validator_rejects_evidence_outside_item_span() -> None:
    """I2: the byte range must sit inside the cited item's own span."""
    item = _make_item()
    inside = _ref(item.start_byte, item.end_byte)
    beyond = _ref(item.end_byte + 5, item.end_byte + 45)  # 40 bytes, past the item
    claim = _claim(inside, beyond)

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I2_span_outside_item" in _codes(report)
    # The in-bounds ref is untouched, so only the bad ref is reported.
    assert sum(code == "I2_span_outside_item" for code in _codes(report)) == 1


def test_validator_rejects_cross_topic_evidence() -> None:
    """I3: the cited item must belong to the topic being validated."""
    item = _make_item()
    # 40 bytes long and otherwise well-formed — only the item id is wrong,
    # so the failure cannot be blamed on span geometry.
    foreign = _ref(ITEM_START_BYTE, ITEM_START_BYTE + 40, item_id="item-other-topic")
    claim = _claim(foreign)

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I3_cross_topic" in _codes(report)
    # No item to measure against -> I2 is not (and cannot be) raised.
    assert "I2_span_outside_item" not in _codes(report)


def test_validator_rejects_evidence_span_too_long() -> None:
    """I8 (Bounded Evidence Contract §3.2): span <= MAX_EVIDENCE_BYTES."""
    long_text = "冗" * 1100          # 3300 UTF-8 bytes
    item = _make_item(item_id="item-big", text=long_text, start_byte=0)
    span_len = len(long_text.encode("utf-8"))
    assert span_len > MAX_EVIDENCE_BYTES
    claim = _claim(_ref(0, span_len, item_id="item-big"))

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I8_span_too_long" in _codes(report)
    assert f"I8_span_too_long:{span_len}" in report.violations
    assert "I7_span_too_short" not in _codes(report)


def test_validator_rejects_evidence_span_too_short() -> None:
    """I7 (Bounded Evidence Contract §3.2): span >= MIN_EVIDENCE_BYTES.
    A 10-byte span is too weak to support a claim. Degenerate spans are
    covered here too: I6 (empty) and I9 (negative offset)."""
    item = _make_item()
    short = _ref(item.start_byte, item.start_byte + 10)
    claim = _claim(short)

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I7_span_too_short" in _codes(report)
    assert f"I7_span_too_short:{10}" in report.violations
    assert "I8_span_too_long" not in _codes(report)

    empty = validate_claim(
        _claim(_ref(item.start_byte, item.start_byte)),
        topic_items=[item],
        topic_id=TOPIC_ID,
    )
    assert "I6_empty_span" in _codes(empty)

    negative = validate_claim(
        _claim(_ref(-5, item.start_byte + 40)),
        topic_items=[item],
        topic_id=TOPIC_ID,
    )
    assert "I9_ref_out_of_bounds" in _codes(negative)


def test_validator_flags_substantive_claim_without_evidence() -> None:
    """I1: a substantive claim must carry >= 1 evidence ref. I10 is the
    defence-in-depth twin for the SUPPORTED-without-evidence case (the
    Claim model has no technical-failure status — Failure Contract §1.3)."""
    item = _make_item()
    substantive = _claim(support=ClaimSupport.SUPPORTED)

    report = validate_claim(substantive, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I1_no_evidence" in _codes(report)
    assert "I10_technical_failure_cannot_be_supported" in _codes(report)
    assert report.needs_reviewer is False   # no refs -> reviewer cannot help

    # Negative control: the legacy placeholder is not substantive, so its
    # total absence of evidence is not a violation.
    placeholder = _claim(
        claim_id="claim-placeholder",
        text="需结合原文核对",
        support=ClaimSupport.INSUFFICIENT_EVIDENCE,
    )
    placeholder_report = validate_claim(
        placeholder, topic_items=[item], topic_id=TOPIC_ID
    )
    assert placeholder_report.violations == []
    assert placeholder_report.is_valid is True


def test_filter_substantive_claims_drops_unsupported() -> None:
    """The render gate: only SUPPORTED claims with >= 1 ref may reach a
    rendered page (unsupported claim 不得进入 rendered page)."""
    item = _make_item()
    good = _ref(item.start_byte, item.end_byte)
    supported_with_refs = _claim(good, claim_id="claim-ok")
    insufficient_with_refs = _claim(
        good, claim_id="claim-insufficient",
        support=ClaimSupport.INSUFFICIENT_EVIDENCE,
    )
    conflicting_with_refs = _claim(
        good, claim_id="claim-conflicting", support=ClaimSupport.CONFLICTING,
    )
    supported_without_refs = _claim(
        claim_id="claim-no-evidence", support=ClaimSupport.SUPPORTED,
    )

    kept = filter_substantive_claims(
        [
            supported_with_refs,
            insufficient_with_refs,
            conflicting_with_refs,
            supported_without_refs,
        ]
    )

    assert [claim.claim_id for claim in kept] == ["claim-ok"]
    # Order of the input is preserved.
    assert kept == [supported_with_refs]
    # The SUPPORTED-without-refs claim is dropped by this gate and would
    # additionally be rejected by I1/I10 in validate_claim.
    assert "I1_no_evidence" in _codes(
        validate_claim(supported_without_refs, topic_items=[item], topic_id=TOPIC_ID)
    )


def test_validator_rejects_duplicate_evidence_refs() -> None:
    """I5: no two refs in one claim may share (item_id, start_byte, end_byte)."""
    item = _make_item()
    first = _ref(item.start_byte, item.end_byte, span_index=0)
    duplicate = _ref(item.start_byte, item.end_byte, span_index=3)
    claim = _claim(first, duplicate)

    report = validate_claim(claim, topic_items=[item], topic_id=TOPIC_ID)

    assert report.is_valid is False
    assert "I5_duplicate_ref" in _codes(report)
    assert sum(code == "I5_duplicate_ref" for code in _codes(report)) == 1


def test_validator_rejects_other_topic_reference() -> None:
    """I4: ``__other__`` is the residual bucket, never a citable source —
    even when the item is (wrongly) listed among the topic's items."""
    other_id = f"item-3{OTHER_TOPIC_ID}"
    other_item = _make_item(item_id=other_id, start_byte=400)
    claim = _claim(_ref(other_item.start_byte, other_item.end_byte, item_id=other_id))

    report = validate_claim(
        claim, topic_items=[_make_item(), other_item], topic_id=TOPIC_ID
    )

    assert report.is_valid is False
    assert "I4_other_topic_ref" in _codes(report)
    # The item *was* present in topic_items, so this is I4 alone, not I3.
    assert "I3_cross_topic" not in _codes(report)


def test_needs_reviewer_only_for_high_risk_supported_with_refs() -> None:
    """Task 17's semantic reviewer is expensive: it is worth invoking only
    for claims that are simultaneously high-risk, claimed-supported, and
    actually carrying evidence."""
    item = _make_item()
    ref = _ref(item.start_byte, item.end_byte)

    high_risk = validate_claim(
        _claim(ref, risk=ClaimRisk.HIGH),
        topic_items=[item],
        topic_id=TOPIC_ID,
    )
    low_risk = validate_claim(
        _claim(ref, risk=ClaimRisk.LOW),
        topic_items=[item],
        topic_id=TOPIC_ID,
    )
    high_risk_unsupported = validate_claim(
        _claim(ref, claim_id="claim-2", support=ClaimSupport.INSUFFICIENT_EVIDENCE,
              risk=ClaimRisk.HIGH),
        topic_items=[item],
        topic_id=TOPIC_ID,
    )

    assert high_risk.needs_reviewer is True
    assert low_risk.needs_reviewer is False
    assert high_risk_unsupported.needs_reviewer is False
    # All three are mechanically valid — needs_reviewer is an economic
    # decision, orthogonal to is_valid.
    assert high_risk.is_valid is True
    assert low_risk.is_valid is True
    assert high_risk_unsupported.is_valid is True
    assert MIN_EVIDENCE_BYTES == 30
