"""Test ClaimParser — opaque dict to structured Claim bridge (Task 2.2)."""
import logging
import time

import pytest

from src.knowledge.claims.model import Claim, ClaimStatus, ClaimType, Evidence
from src.knowledge.claims.parser import ClaimParser
from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_llm_output():
    return {
        "model": "claude-sonnet-4-20250514",
        "choices": [{"content": "extracted claims..."}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


@pytest.fixture
def basic_evidence():
    return [
        {"source_path": "/docs/astro.pdf", "page": 3, "quote": "Earth revolves around Sun."},
        {"source_path": "/docs/astro.pdf", "page": 5, "quote": "Moon is Earth's satellite."},
    ]


@pytest.fixture
def basic_claims():
    return [
        {"statement": "Earth orbits the Sun", "confidence": 0.95, "evidence_refs": [0]},
        {"statement": "The Moon orbits Earth", "confidence": 0.90, "evidence_refs": [1]},
    ]


def make_candidate(
    id="cand-001",
    source_id="doc-001",
    claims=None,
    evidence=None,
    confidence=0.85,
):
    """Helper to build a KnowledgeCandidate with minimal boilerplate."""
    return KnowledgeCandidate(
        id=id,
        source_id=source_id,
        type=KnowledgeType.CLAIM,
        title="Test Candidate",
        claims=claims if claims is not None else [],
        confidence=confidence,
        evidence=evidence if evidence is not None else [],
        raw_llm_output={"model": "test"},
    )


# ---------------------------------------------------------------------------
# Test: basic extraction
# ---------------------------------------------------------------------------


class TestBasicExtraction:
    """Extract structured Claims from a candidate with valid data."""

    def test_extracts_two_claims(self, basic_claims, basic_evidence):
        """2 claims + 2 evidence items → 2 Claims with correct statements."""
        candidate = make_candidate(claims=basic_claims, evidence=basic_evidence)
        results = ClaimParser.extract(candidate)

        assert len(results) == 2
        assert all(isinstance(c, Claim) for c in results)
        assert results[0].statement == "Earth orbits the Sun"
        assert results[1].statement == "The Moon orbits Earth"

    def test_extracts_correct_confidence(self, basic_claims, basic_evidence):
        """Each claim retains its confidence value."""
        candidate = make_candidate(claims=basic_claims, evidence=basic_evidence)
        results = ClaimParser.extract(candidate)

        assert results[0].confidence == 0.95
        assert results[1].confidence == 0.90

    def test_extracts_correct_evidence_count(self, basic_claims, basic_evidence):
        """Each claim has the correct number of Evidence objects."""
        candidate = make_candidate(claims=basic_claims, evidence=basic_evidence)
        results = ClaimParser.extract(candidate)

        assert len(results[0].evidence) == 1
        assert len(results[1].evidence) == 1


# ---------------------------------------------------------------------------
# Test: evidence_refs resolution
# ---------------------------------------------------------------------------


class TestEvidenceRefsResolution:
    """evidence_refs indices are correctly resolved to Evidence objects."""

    def test_refs_resolve_to_correct_evidence(self):
        """claims[0] refs evidence[0], claims[1] refs evidence[1]."""
        evidence = [
            {"source_path": "/a.pdf", "page": 1, "quote": "first quote"},
            {"source_path": "/b.pdf", "page": 2, "quote": "second quote"},
        ]
        claims = [
            {"statement": "Claim 0", "confidence": 0.9, "evidence_refs": [0]},
            {"statement": "Claim 1", "confidence": 0.8, "evidence_refs": [1]},
        ]
        candidate = make_candidate(claims=claims, evidence=evidence)
        results = ClaimParser.extract(candidate)

        assert results[0].evidence[0].source_path == "/a.pdf"
        assert results[0].evidence[0].page == 1
        assert results[0].evidence[0].quote == "first quote"

        assert results[1].evidence[0].source_path == "/b.pdf"
        assert results[1].evidence[0].page == 2
        assert results[1].evidence[0].quote == "second quote"


# ---------------------------------------------------------------------------
# Test: shared evidence
# ---------------------------------------------------------------------------


class TestSharedEvidence:
    """Two claims can reference the same evidence index."""

    def test_shared_evidence_ref(self):
        """Both claims reference evidence[0] — both get the same Evidence."""
        evidence = [{"source_path": "/shared.pdf", "page": 1, "quote": "shared quote"}]
        claims = [
            {"statement": "Claim A", "confidence": 0.9, "evidence_refs": [0]},
            {"statement": "Claim B", "confidence": 0.8, "evidence_refs": [0]},
        ]
        candidate = make_candidate(claims=claims, evidence=evidence)
        results = ClaimParser.extract(candidate)

        # Both claims have the same evidence data
        assert results[0].evidence[0].source_path == "/shared.pdf"
        assert results[1].evidence[0].source_path == "/shared.pdf"
        assert results[0].evidence[0].quote == "shared quote"
        assert results[1].evidence[0].quote == "shared quote"


# ---------------------------------------------------------------------------
# Test: missing statement
# ---------------------------------------------------------------------------


class TestMissingStatement:
    """Claim dicts without a 'statement' key are skipped with a warning."""

    def test_missing_statement_skipped(self, caplog):
        """One claim missing 'statement' → skipped, others still extracted."""
        claims = [
            {"statement": "Valid claim", "confidence": 0.9, "evidence_refs": []},
            {"confidence": 0.5, "evidence_refs": []},  # missing 'statement'
            {"statement": "Another valid", "confidence": 0.7, "evidence_refs": []},
        ]
        candidate = make_candidate(claims=claims)
        results = ClaimParser.extract(candidate)

        assert len(results) == 2
        assert results[0].statement == "Valid claim"
        assert results[1].statement == "Another valid"

    def test_missing_statement_logs_warning(self, caplog):
        """Warning is logged when a claim dict has no 'statement'."""
        claims = [
            {"statement": "Valid claim", "confidence": 0.9, "evidence_refs": []},
            {"confidence": 0.5, "evidence_refs": []},  # missing 'statement'
        ]
        candidate = make_candidate(claims=claims)
        with caplog.at_level(logging.WARNING):
            ClaimParser.extract(candidate)

        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("statement" in w.lower() for w in warnings), (
            f"Expected warning about missing statement, got: {warnings}"
        )


# ---------------------------------------------------------------------------
# Test: empty claims list
# ---------------------------------------------------------------------------


class TestEmptyClaimsList:
    """Empty claims list returns empty list."""

    def test_empty_claims_returns_empty_list(self):
        """An empty claims list should return an empty list."""
        candidate = make_candidate(claims=[])
        results = ClaimParser.extract(candidate)
        assert results == []

    def test_none_claims_empty_list(self):
        """candidate with no evidence and no claims returns [].

        (Behavior: if claims=[], result is [] regardless of evidence.)
        """
        candidate = make_candidate(claims=[], evidence=[])
        results = ClaimParser.extract(candidate)
        assert results == []


# ---------------------------------------------------------------------------
# Test: evidence_refs out of range
# ---------------------------------------------------------------------------


class TestEvidenceRefsOutOfRange:
    """Out-of-range evidence_refs indices are skipped with a warning."""

    def test_out_of_range_ref_skipped(self, caplog):
        """evidence_refs index >= len(evidence) → skip that ref, still produce claim."""
        evidence = [{"source_path": "/a.pdf", "page": 1, "quote": "only evidence"}]
        claims = [
            {
                "statement": "Has bad ref",
                "confidence": 0.9,
                "evidence_refs": [0, 99],  # 99 is out of range
            },
        ]
        candidate = make_candidate(claims=claims, evidence=evidence)
        with caplog.at_level(logging.WARNING):
            results = ClaimParser.extract(candidate)

        assert len(results) == 1
        assert len(results[0].evidence) == 1  # only the valid ref [0]
        assert results[0].evidence[0].source_path == "/a.pdf"

        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("out of range" in w.lower() for w in warnings), (
            f"Expected warning about out-of-range ref, got: {warnings}"
        )

    def test_negative_ref_skipped(self, caplog):
        """Negative evidence_refs indices are skipped."""
        evidence = [{"source_path": "/a.pdf", "page": 1, "quote": "q"}]
        claims = [
            {
                "statement": "Has negative ref",
                "confidence": 0.5,
                "evidence_refs": [-1],
            },
        ]
        candidate = make_candidate(claims=claims, evidence=evidence)
        with caplog.at_level(logging.WARNING):
            results = ClaimParser.extract(candidate)

        assert len(results) == 1
        assert results[0].evidence == []


# ---------------------------------------------------------------------------
# Test: default confidence
# ---------------------------------------------------------------------------


class TestDefaultConfidence:
    """Claim dict without 'confidence' key → default 0.5."""

    def test_missing_confidence_defaults_to_0_5(self):
        """No 'confidence' key in claim dict → Claim.confidence = 0.5."""
        claims = [{"statement": "No confidence key", "evidence_refs": []}]
        candidate = make_candidate(claims=claims)
        results = ClaimParser.extract(candidate)

        assert len(results) == 1
        assert results[0].confidence == 0.5


# ---------------------------------------------------------------------------
# Test: evidence_refs defaults to empty list
# ---------------------------------------------------------------------------


class TestDefaultEvidenceRefs:
    """Claim dict without 'evidence_refs' key → default [].

    (The spec does NOT require confidence to default to candidate confidence.)
    """

    def test_missing_evidence_refs_defaults_to_empty(self):
        """No 'evidence_refs' key in claim dict → Claim.evidence = []."""
        claims = [{"statement": "No evidence refs", "confidence": 0.8}]
        candidate = make_candidate(
            claims=claims,
            evidence=[{"source_path": "/unused.pdf", "page": 1, "quote": "q"}],
        )
        results = ClaimParser.extract(candidate)

        assert len(results) == 1
        assert results[0].evidence == []


# ---------------------------------------------------------------------------
# Test: claim id format
# ---------------------------------------------------------------------------


class TestClaimIdFormat:
    """Claim ids are generated as candidate.id + '_c' + index."""

    def test_claim_id_format(self):
        """candidate.id='abc123', 3 claims → ids: abc123_c0, abc123_c1, abc123_c2."""
        claims = [
            {"statement": "Claim 0", "confidence": 0.9, "evidence_refs": []},
            {"statement": "Claim 1", "confidence": 0.8, "evidence_refs": []},
            {"statement": "Claim 2", "confidence": 0.7, "evidence_refs": []},
        ]
        candidate = make_candidate(id="abc123", claims=claims)
        results = ClaimParser.extract(candidate)

        assert results[0].id == "abc123_c0"
        assert results[1].id == "abc123_c1"
        assert results[2].id == "abc123_c2"

    def test_claim_id_with_complex_candidate_id(self):
        """Works with any candidate ID format."""
        candidate = make_candidate(
            id="card_001abc_def456_some-slug",
            claims=[{"statement": "X", "confidence": 0.5, "evidence_refs": []}],
        )
        results = ClaimParser.extract(candidate)
        assert results[0].id == "card_001abc_def456_some-slug_c0"


# ---------------------------------------------------------------------------
# Test: source_objects set
# ---------------------------------------------------------------------------


class TestSourceObjects:
    """Each Claim's source_objects = [candidate.source_id]."""

    def test_source_objects_contain_candidate_source_id(self):
        """source_objects on each claim is a list containing the candidate's source_id."""
        claims = [
            {"statement": "C1", "confidence": 0.9, "evidence_refs": []},
            {"statement": "C2", "confidence": 0.7, "evidence_refs": []},
        ]
        candidate = make_candidate(source_id="doc-astro-42", claims=claims)
        results = ClaimParser.extract(candidate)

        assert results[0].source_objects == ["doc-astro-42"]
        assert results[1].source_objects == ["doc-astro-42"]


# ---------------------------------------------------------------------------
# Test: default ClaimType is FACT
# ---------------------------------------------------------------------------


class TestDefaultClaimTypeIsFact:
    """All claims get type=FACT (Analyzer doesn't classify claim type yet)."""

    def test_all_claims_are_fact_type(self):
        """Every extracted Claim has type=ClaimType.FACT."""
        claims = [
            {"statement": "S1", "confidence": 0.9, "evidence_refs": []},
            {"statement": "S2", "confidence": 0.5, "evidence_refs": [0]},
        ]
        candidate = make_candidate(
            claims=claims,
            evidence=[{"source_path": "/x.pdf", "page": 1, "quote": "q"}],
        )
        results = ClaimParser.extract(candidate)

        for c in results:
            assert c.type == ClaimType.FACT, f"Claim {c.id} has type {c.type}, expected FACT"


# ---------------------------------------------------------------------------
# Test: default ClaimStatus is PENDING
# ---------------------------------------------------------------------------


class TestDefaultClaimStatusIsPending:
    """All claims get status=PENDING."""

    def test_all_claims_are_pending_status(self):
        """Every extracted Claim has status=ClaimStatus.PENDING."""
        claims = [
            {"statement": "S1", "confidence": 0.9, "evidence_refs": []},
            {"statement": "S2", "confidence": 0.5, "evidence_refs": []},
        ]
        candidate = make_candidate(claims=claims)
        results = ClaimParser.extract(candidate)

        for c in results:
            assert c.status == ClaimStatus.PENDING, (
                f"Claim {c.id} has status {c.status}, expected PENDING"
            )


# ---------------------------------------------------------------------------
# Test: mixed valid/invalid claims
# ---------------------------------------------------------------------------


class TestMixedValidInvalidClaims:
    """When some claims are invalid and some are valid, only valid ones are returned."""

    def test_middle_claim_missing_statement(self):
        """3 claims, middle missing 'statement' → 2 Claims returned."""
        claims = [
            {"statement": "First", "confidence": 0.9, "evidence_refs": []},
            {"confidence": 0.5, "evidence_refs": []},  # missing statement
            {"statement": "Third", "confidence": 0.7, "evidence_refs": []},
        ]
        candidate = make_candidate(claims=claims)
        results = ClaimParser.extract(candidate)

        assert len(results) == 2
        assert results[0].statement == "First"
        assert results[1].statement == "Third"
        # IDs should be sequential based on position (skipped claim doesn't get an ID)
        assert results[0].id == "cand-001_c0"
        assert results[1].id == "cand-001_c1"


# ---------------------------------------------------------------------------
# Test: multiple evidence per claim
# ---------------------------------------------------------------------------


class TestMultipleEvidencePerClaim:
    """A claim can reference multiple evidence items."""

    def test_multiple_evidence_refs(self):
        """claims[0] has evidence_refs=[0,1] → 2 Evidence objects attached."""
        evidence = [
            {"source_path": "/a.pdf", "page": 1, "quote": "first"},
            {"source_path": "/b.pdf", "page": 2, "quote": "second"},
        ]
        claims = [
            {"statement": "Multi evidence", "confidence": 0.9, "evidence_refs": [0, 1]},
        ]
        candidate = make_candidate(claims=claims, evidence=evidence)
        results = ClaimParser.extract(candidate)

        assert len(results) == 1
        assert len(results[0].evidence) == 2
        assert results[0].evidence[0].source_path == "/a.pdf"
        assert results[0].evidence[0].quote == "first"
        assert results[0].evidence[1].source_path == "/b.pdf"
        assert results[0].evidence[1].quote == "second"
