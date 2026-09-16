"""Tests for canonical claim projection (Task 44)."""
from __future__ import annotations

from src.pipeline.v7_extract.claim import Claim, EvidenceRef
from src.reconciliation.canonical_claim_models import (
    CanonicalClaim,
    ClaimReconciliationDecision,
)
from src.reconciliation.canonical_claim_projection import (
    CanonicalClaimView,
    CanonicalViewKind,
    project_canonical_view,
)


def _make_claim(claim_id: str, text: str, confidence: float = 0.9,
                ref: EvidenceRef | None = None) -> Claim:
    return Claim(
        claim_id=claim_id,
        slot_name="definition",
        text=text,
        evidence_refs=[ref] if ref else [],
        confidence=confidence,
    )


def _make_ref(item_id: str = "i1", start: int = 0, end: int = 100) -> EvidenceRef:
    return EvidenceRef(
        item_id=item_id, item_index=0, span_index=0,
        start_byte=start, end_byte=end,
    )


def test_projection_same_uses_consensus_text():
    """3 SAME members → text = 最高 confidence member + member_summary 列所有"""
    c1 = _make_claim("c1", "low-conf text", confidence=0.5)
    c2 = _make_claim("c2", "high-conf text", confidence=0.95)
    c3 = _make_claim("c3", "mid-conf text", confidence=0.7)
    canonical = CanonicalClaim(
        canonical_claim_id="cc-1",
        canonical_id="c-aaaa",
        text="placeholder",
        member_claim_ids=["c1", "c2", "c3"],
        decision=ClaimReconciliationDecision.SAME,
        confidence=0.0,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [c1, c2, c3])
    assert isinstance(view, CanonicalClaimView)
    assert view.view_kind is CanonicalViewKind.SAME
    # Highest-confidence member text wins.
    assert view.text == "high-conf text"
    # Confidence is average.
    assert abs(view.confidence - (0.5 + 0.95 + 0.7) / 3) < 1e-9
    # Member summary mentions all 3 members.
    assert "3 members" in view.member_summary
    assert "SAME" in view.member_summary


def test_projection_overlap_lists_all_texts():
    """3 OVERLAP members → text = 三段以 \\n 分隔"""
    c1 = _make_claim("c1", "alpha text")
    c2 = _make_claim("c2", "beta text")
    c3 = _make_claim("c3", "gamma text")
    canonical = CanonicalClaim(
        canonical_claim_id="cc-2",
        canonical_id="c-bbbb",
        text="placeholder",
        member_claim_ids=["c1", "c2", "c3"],
        decision=ClaimReconciliationDecision.OVERLAP,
        confidence=0.0,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [c1, c2, c3])
    assert view.view_kind is CanonicalViewKind.OVERLAP
    assert "alpha text" in view.text
    assert "beta text" in view.text
    assert "gamma text" in view.text
    # Joined by \n (not \n---\n).
    assert "\n---\n" not in view.text
    assert view.text.count("\n") == 2


def test_projection_conflict_lists_separately():
    """2 CONFLICT members → text = 两段以 \\n---\\n 分隔"""
    c1 = _make_claim("c1", "view A: X is true")
    c2 = _make_claim("c2", "view B: X is false")
    canonical = CanonicalClaim(
        canonical_claim_id="cc-3",
        canonical_id="c-cccc",
        text="placeholder",
        member_claim_ids=["c1", "c2"],
        decision=ClaimReconciliationDecision.CONFLICT,
        confidence=0.0,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [c1, c2])
    assert view.view_kind is CanonicalViewKind.CONFLICT
    assert "view A: X is true" in view.text
    assert "view B: X is false" in view.text
    assert "\n---\n" in view.text


def test_projection_single_uses_member_text_directly():
    """SINGLE → text = single member text directly"""
    c1 = _make_claim("c1", "single text here", confidence=0.8)
    canonical = CanonicalClaim(
        canonical_claim_id="cc-4",
        canonical_id="c-dddd",
        text="placeholder",
        member_claim_ids=["c1"],
        decision=ClaimReconciliationDecision.SINGLE,
        confidence=0.0,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [c1])
    assert view.view_kind is CanonicalViewKind.SINGLE
    assert view.text == "single text here"
    # Confidence comes from the single member's confidence.
    assert view.confidence == 0.8
    assert "1 member" in view.member_summary


def test_projection_dedups_evidence_refs():
    """Same (item_id, start, end) appears in 2 members → dedup to 1."""
    ref_a = _make_ref(item_id="i1", start=0, end=100)
    ref_b = _make_ref(item_id="i1", start=0, end=100)  # exact duplicate
    ref_c = _make_ref(item_id="i1", start=200, end=300)  # different range
    c1 = _make_claim("c1", "text 1", ref=ref_a)
    c2 = _make_claim("c2", "text 2", ref=ref_b)
    c3 = _make_claim("c3", "text 3", ref=ref_c)
    canonical = CanonicalClaim(
        canonical_claim_id="cc-5",
        canonical_id="c-eeee",
        text="placeholder",
        member_claim_ids=["c1", "c2", "c3"],
        decision=ClaimReconciliationDecision.SAME,
        confidence=0.0,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [c1, c2, c3])
    # 2 unique refs: (i1, 0, 100) + (i1, 200, 300).
    assert len(view.evidence_refs) == 2
    keys = {(r.item_id, r.start_byte, r.end_byte) for r in view.evidence_refs}
    assert ("i1", 0, 100) in keys
    assert ("i1", 200, 300) in keys


def test_projection_empty_members_falls_back_to_canonical_text():
    """0 members → text = canonical_claim.text placeholder; no crash."""
    canonical = CanonicalClaim(
        canonical_claim_id="cc-6",
        canonical_id="c-ffff",
        text="placeholder text",
        member_claim_ids=[],
        decision=ClaimReconciliationDecision.SINGLE,
        confidence=0.5,
        support_kind=None,
        created_at_ms=0,
        updated_at_ms=0,
    )
    view = project_canonical_view(canonical, [])
    assert view.text == "placeholder text"
    assert "0 members" in view.member_summary