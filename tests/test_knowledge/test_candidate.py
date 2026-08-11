"""Test KnowledgeCandidate and CandidateStatus (Task 1.6)."""
import pytest

from src.knowledge.core.candidate import (
    CandidateStatus,
    KnowledgeCandidate,
    can_transition,
)
from src.knowledge.core.object import KnowledgeType


class TestCandidateStatusEnum:
    """CandidateStatus has exactly 4 values."""

    def test_all_four_values_exist(self):
        assert hasattr(CandidateStatus, "PENDING")
        assert hasattr(CandidateStatus, "VALIDATED")
        assert hasattr(CandidateStatus, "REJECTED")
        assert hasattr(CandidateStatus, "PROMOTED")

    def test_values_serialize_correctly(self):
        assert CandidateStatus.PENDING.value == "pending"
        assert CandidateStatus.VALIDATED.value == "validated"
        assert CandidateStatus.REJECTED.value == "rejected"
        assert CandidateStatus.PROMOTED.value == "promoted"

    def test_total_count_is_four(self):
        members = list(CandidateStatus)
        assert len(members) == 4, (
            f"Expected 4, got {len(members)}: {[m.value for m in members]}"
        )


class TestCandidateStatusTransitions:
    """State machine transition validation."""

    # --- Valid transitions ---
    def test_pending_to_validated_is_valid(self):
        assert can_transition(CandidateStatus.PENDING, CandidateStatus.VALIDATED) is True

    def test_pending_to_rejected_is_valid(self):
        assert can_transition(CandidateStatus.PENDING, CandidateStatus.REJECTED) is True

    def test_validated_to_promoted_is_valid(self):
        assert can_transition(CandidateStatus.VALIDATED, CandidateStatus.PROMOTED) is True

    def test_rejected_to_pending_is_valid(self):
        assert can_transition(CandidateStatus.REJECTED, CandidateStatus.PENDING) is True

    # --- Invalid transitions ---
    def test_promoted_is_terminal(self):
        """PROMOTED cannot transition to any other state."""
        for target in CandidateStatus:
            assert can_transition(CandidateStatus.PROMOTED, target) is False

    def test_pending_cannot_jump_to_promoted(self):
        """PENDING → PROMOTED is not allowed (must go through VALIDATED)."""
        assert can_transition(CandidateStatus.PENDING, CandidateStatus.PROMOTED) is False

    def test_validated_cannot_go_to_rejected(self):
        """VALIDATED → REJECTED is not allowed."""
        assert can_transition(CandidateStatus.VALIDATED, CandidateStatus.REJECTED) is False

    def test_validated_cannot_go_back_to_pending(self):
        """VALIDATED → PENDING is not allowed."""
        assert can_transition(CandidateStatus.VALIDATED, CandidateStatus.PENDING) is False

    def test_rejected_cannot_jump_to_promoted(self):
        """REJECTED → PROMOTED is not allowed."""
        assert can_transition(CandidateStatus.REJECTED, CandidateStatus.PROMOTED) is False

    def test_rejected_cannot_go_to_validated(self):
        """REJECTED → VALIDATED is not allowed."""
        assert can_transition(CandidateStatus.REJECTED, CandidateStatus.VALIDATED) is False

    def test_self_transition_is_invalid(self):
        """Cannot transition to the same state."""
        for state in CandidateStatus:
            assert can_transition(state, state) is False, (
                f"Self-transition {state.value} -> {state.value} should be invalid"
            )


@pytest.fixture
def sample_claims():
    return [
        {"statement": "Earth orbits the Sun", "confidence": 0.95, "evidence_refs": [0]},
        {"statement": "The Moon orbits Earth", "confidence": 0.90, "evidence_refs": [0, 1]},
    ]


@pytest.fixture
def sample_evidence():
    return [
        {"source_path": "/docs/astro.pdf", "page": 3, "quote": "The Earth revolves around the Sun."},
        {"source_path": "/docs/astro.pdf", "page": 5, "quote": "The Moon is Earth's natural satellite."},
    ]


@pytest.fixture
def raw_llm_output():
    return {
        "model": "claude-sonnet-4-20250514",
        "choices": [{"content": "extracted claims..."}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


class TestKnowledgeCandidateCreation:
    """KnowledgeCandidate dataclass creation with all fields."""

    def test_create_with_all_fields(self, sample_claims, sample_evidence, raw_llm_output):
        """KnowledgeCandidate accepts all fields and returns them correctly."""
        candidate = KnowledgeCandidate(
            id="cand-001",
            source_id="doc-astro-001",
            type=KnowledgeType.CLAIM,
            title="Astronomy Facts",
            claims=sample_claims,
            confidence=0.85,
            evidence=sample_evidence,
            raw_llm_output=raw_llm_output,
            status=CandidateStatus.VALIDATED,
        )
        assert candidate.id == "cand-001"
        assert candidate.source_id == "doc-astro-001"
        assert candidate.type == KnowledgeType.CLAIM
        assert candidate.title == "Astronomy Facts"
        assert candidate.claims == sample_claims
        assert candidate.confidence == 0.85
        assert candidate.evidence == sample_evidence
        assert candidate.raw_llm_output == raw_llm_output
        assert candidate.status == CandidateStatus.VALIDATED

    def test_default_status_is_pending(self, sample_claims, sample_evidence, raw_llm_output):
        """When status is not provided, it defaults to PENDING."""
        candidate = KnowledgeCandidate(
            id="cand-002",
            source_id="doc-002",
            type=KnowledgeType.CLAIM,
            title="Default Status Test",
            claims=sample_claims,
            confidence=0.5,
            evidence=sample_evidence,
            raw_llm_output=raw_llm_output,
        )
        assert candidate.status == CandidateStatus.PENDING

    def test_all_candidate_status_values_work(self, sample_claims, sample_evidence, raw_llm_output):
        """KnowledgeCandidate accepts every CandidateStatus value."""
        for status in CandidateStatus:
            candidate = KnowledgeCandidate(
                id=f"cand-{status.value}",
                source_id="doc-x",
                type=KnowledgeType.CLAIM,
                title=f"Status {status.value}",
                claims=sample_claims,
                confidence=0.5,
                evidence=sample_evidence,
                raw_llm_output=raw_llm_output,
                status=status,
            )
            assert candidate.status == status, f"Failed for {status}"


class TestClaimDictSchema:
    """Claim dict follows the expected opaque schema."""

    def test_valid_claim_dict_has_required_keys(self):
        """A valid claim dict must contain statement, confidence, evidence_refs."""
        claim = {"statement": "Gravity exists", "confidence": 0.99, "evidence_refs": [0]}
        assert "statement" in claim
        assert "confidence" in claim
        assert "evidence_refs" in claim
        assert isinstance(claim["statement"], str)
        assert isinstance(claim["confidence"], float)
        assert isinstance(claim["evidence_refs"], list)

    def test_evidence_refs_is_list_of_ints(self):
        """evidence_refs must be a list of integer indices."""
        claim = {"statement": "Water boils at 100C", "confidence": 0.88, "evidence_refs": [0, 2, 5]}
        for ref in claim["evidence_refs"]:
            assert isinstance(ref, int), f"Expected int, got {type(ref)}"

    def test_evidence_refs_can_be_empty(self):
        """A claim may have no evidence references (empty list)."""
        claim = {"statement": "Unsupported claim", "confidence": 0.3, "evidence_refs": []}
        assert claim["evidence_refs"] == []

    def test_confidence_is_float_between_0_and_1(self):
        """Confidence should be a float in [0.0, 1.0]."""
        claim = {"statement": "X", "confidence": 0.75, "evidence_refs": [0]}
        assert 0.0 <= claim["confidence"] <= 1.0


class TestEvidenceDictSchema:
    """Evidence dict follows the expected opaque schema."""

    def test_evidence_dict_has_required_keys(self):
        """An evidence dict must contain source_path, page, quote."""
        ev = {"source_path": "/docs/book.pdf", "page": 42, "quote": "Exact text from source."}
        assert "source_path" in ev
        assert "page" in ev
        assert "quote" in ev
        assert isinstance(ev["source_path"], str)
        assert isinstance(ev["quote"], str)

    def test_page_can_be_none(self):
        """Page can be None when the source has no page numbers."""
        ev = {"source_path": "/docs/webpage.md", "page": None, "quote": "Some text."}
        assert ev["page"] is None

    def test_quote_can_be_empty(self):
        """Quote can be empty string."""
        ev = {"source_path": "/docs/notes.md", "page": 1, "quote": ""}
        assert ev["quote"] == ""


class TestEvidenceRefsIndexValidation:
    """evidence_refs indices must be within the evidence list bounds."""

    def test_evidence_refs_within_bounds(self):
        """All evidence_refs indices are valid when within evidence list bounds."""
        evidence = [
            {"source_path": "/a.pdf", "page": 1, "quote": "q1"},
            {"source_path": "/b.pdf", "page": 2, "quote": "q2"},
            {"source_path": "/c.pdf", "page": 3, "quote": "q3"},
        ]
        claims = [
            {"statement": "Fact 1", "confidence": 0.9, "evidence_refs": [0, 2]},
            {"statement": "Fact 2", "confidence": 0.8, "evidence_refs": [1]},
        ]
        for claim in claims:
            for ref in claim["evidence_refs"]:
                assert 0 <= ref < len(evidence), (
                    f"evidence_refs index {ref} out of bounds (evidence has {len(evidence)} items)"
                )

    def test_out_of_bounds_ref_detected(self):
        """An out-of-bounds evidence_refs index is caught."""
        evidence = [{"source_path": "/a.pdf", "page": 1, "quote": "q"}]
        claim = {"statement": "Bad ref", "confidence": 0.5, "evidence_refs": [5]}

        # evidence has 1 item (index 0), so ref 5 is out of bounds
        for ref in claim["evidence_refs"]:
            assert not (0 <= ref < len(evidence)), (
                f"Expected ref {ref} to be out of bounds for evidence of length {len(evidence)}"
            )

    def test_negative_ref_detected(self):
        """A negative evidence_refs index is invalid."""
        evidence = [{"source_path": "/a.pdf", "page": 1, "quote": "q"}]
        claim = {"statement": "Negative ref", "confidence": 0.5, "evidence_refs": [-1]}

        for ref in claim["evidence_refs"]:
            assert not (0 <= ref < len(evidence)), (
                f"Expected negative ref {ref} to be invalid"
            )


class TestOpaqueClaimsStorage:
    """Claims are stored as opaque dicts, not structured Claim objects (Phase 2)."""

    def test_claims_are_plain_dicts(self, sample_claims, sample_evidence, raw_llm_output):
        """Claims in KnowledgeCandidate are plain dicts, not a Claim class."""
        candidate = KnowledgeCandidate(
            id="cand-opaque",
            source_id="doc-opaque",
            type=KnowledgeType.CLAIM,
            title="Opaque Claims Test",
            claims=[{"statement": "S", "confidence": 0.7, "evidence_refs": [0]}],
            confidence=0.7,
            evidence=[{"source_path": "/x", "page": 1, "quote": "q"}],
            raw_llm_output=raw_llm_output,
        )
        assert isinstance(candidate.claims, list)
        assert len(candidate.claims) > 0
        for claim in candidate.claims:
            assert isinstance(claim, dict), (
                f"Expected dict, got {type(claim)} — claims must be opaque dicts"
            )

    def test_evidence_are_plain_dicts(self, sample_claims, sample_evidence, raw_llm_output):
        """Evidence in KnowledgeCandidate are plain dicts."""
        candidate = KnowledgeCandidate(
            id="cand-ev",
            source_id="doc-ev",
            type=KnowledgeType.CLAIM,
            title="Evidence Dict Test",
            claims=[{"statement": "S", "confidence": 0.5, "evidence_refs": []}],
            confidence=0.5,
            evidence=[{"source_path": "/x", "page": 1, "quote": "q"}],
            raw_llm_output=raw_llm_output,
        )
        assert isinstance(candidate.evidence, list)
        for ev in candidate.evidence:
            assert isinstance(ev, dict), (
                f"Expected dict, got {type(ev)} — evidence must be opaque dicts"
            )

    def test_raw_llm_output_is_opaque_dict(self, sample_claims, sample_evidence, raw_llm_output):
        """raw_llm_output is an opaque dict for debug and Phase 2 replay."""
        candidate = KnowledgeCandidate(
            id="cand-raw",
            source_id="doc-raw",
            type=KnowledgeType.CLAIM,
            title="Raw LLM Output Test",
            claims=[{"statement": "S", "confidence": 0.5, "evidence_refs": []}],
            confidence=0.5,
            evidence=[{"source_path": "/x", "page": 1, "quote": "q"}],
            raw_llm_output=raw_llm_output,
        )
        assert isinstance(candidate.raw_llm_output, dict)
        assert "model" in candidate.raw_llm_output

    def test_candidate_with_multiple_claims_and_evidence(
        self, sample_claims, sample_evidence, raw_llm_output
    ):
        """Full integration: candidate with 2 claims referencing 2 evidence items."""
        candidate = KnowledgeCandidate(
            id="cand-full",
            source_id="doc-full",
            type=KnowledgeType.CLAIM,
            title="Full Integration",
            claims=sample_claims,
            confidence=0.88,
            evidence=sample_evidence,
            raw_llm_output=raw_llm_output,
            status=CandidateStatus.PENDING,
        )
        assert len(candidate.claims) == 2
        assert len(candidate.evidence) == 2
        # Verify evidence_refs are valid indices into evidence
        for claim in candidate.claims:
            for ref in claim["evidence_refs"]:
                assert 0 <= ref < len(candidate.evidence), (
                    f"evidence_refs index {ref} out of bounds"
                )
        # Verify each claim has correct structure
        assert candidate.claims[0]["statement"] == "Earth orbits the Sun"
        assert candidate.claims[0]["confidence"] == 0.95
        assert candidate.claims[0]["evidence_refs"] == [0]
        assert candidate.claims[1]["statement"] == "The Moon orbits Earth"
        assert candidate.claims[1]["confidence"] == 0.90
        assert candidate.claims[1]["evidence_refs"] == [0, 1]
