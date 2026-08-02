"""Tests for src/pipeline/stages/candidate_promoter.py — CandidatePromoter bridge."""
import time

import pytest

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)


# ---------------------------------------------------------------------------
# Helper: build a VALIDATED candidate
# ---------------------------------------------------------------------------
def _make_validated_candidate(**overrides) -> KnowledgeCandidate:
    defaults = dict(
        id="cand-001",
        source_id="src-001",
        type=KnowledgeType.CONCEPT,
        title="Test Concept",
        claims=[{"text": "Claim A", "evidence_refs": [0]}],
        confidence=0.85,
        evidence=[{"source_path": "/path/to/source.pdf", "quote": "evidence quote"}],
        raw_llm_output={"raw": "data"},
        status=CandidateStatus.VALIDATED,
    )
    defaults.update(overrides)
    return KnowledgeCandidate(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestCandidatePromoterSuccess:
    """Happy path: VALIDATED candidate → KnowledgeObject."""

    def test_promote_returns_knowledge_object(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate()
        obj = promoter.promote(candidate)

        assert isinstance(obj, KnowledgeObject)

    def test_promote_sets_all_fields_correctly(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        now = int(time.time() * 1000)
        candidate = _make_validated_candidate(
            id="cand-002",
            source_id="src-002",
            type=KnowledgeType.ENTITY,
            title="Test Entity",
            confidence=0.92,
        )

        obj = promoter.promote(candidate)

        assert obj.id == "cand-002"
        assert obj.type == KnowledgeType.ENTITY
        assert obj.title == "Test Entity"
        assert obj.confidence == 0.92
        assert obj.grade == "B"
        assert obj.heat == 50
        assert obj.relations == []
        assert obj.created_at >= now
        assert obj.updated_at >= now

    def test_shared_id_between_candidate_and_object(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate(id="shared-id-123")
        obj = promoter.promote(candidate)

        assert obj.id == candidate.id
        assert obj.id == "shared-id-123"

    def test_content_is_empty_string(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate()
        obj = promoter.promote(candidate)

        assert obj.content == ""

    def test_lifecycle_is_processing(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate()
        obj = promoter.promote(candidate)

        assert obj.lifecycle == LifecycleState.PROCESSING

    def test_provenance_built_from_candidate(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        now = int(time.time() * 1000)
        candidate = _make_validated_candidate(source_id="src-provenance-test")

        obj = promoter.promote(candidate)

        assert isinstance(obj.provenance, Provenance)
        assert obj.provenance.source_path == "src-provenance-test"
        assert obj.provenance.page is None
        assert obj.provenance.quote == ""
        assert obj.provenance.ingestor_version == "2.0.0"
        assert obj.provenance.ingested_at >= now

    def test_versions_has_initial_v1_entry(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        now = int(time.time() * 1000)
        candidate = _make_validated_candidate()

        obj = promoter.promote(candidate)

        assert len(obj.versions) == 1
        v = obj.versions[0]
        assert isinstance(v, VersionRef)
        assert v.version_id == "v1"
        assert v.timestamp >= now
        assert v.change_description == "created from candidate"

    def test_candidate_status_changes_to_promoted(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate()

        assert candidate.status == CandidateStatus.VALIDATED
        promoter.promote(candidate)
        assert candidate.status == CandidateStatus.PROMOTED

    def test_heat_initial_value_is_50(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate()
        obj = promoter.promote(candidate)

        assert obj.heat == 50


class TestCandidatePromoterValidation:
    """Rejects non-VALIDATED candidates."""

    def test_pending_candidate_raises_value_error(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate(status=CandidateStatus.PENDING)

        with pytest.raises(ValueError, match="VALIDATED"):
            promoter.promote(candidate)

    def test_rejected_candidate_raises_value_error(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate(status=CandidateStatus.REJECTED)

        with pytest.raises(ValueError, match="VALIDATED"):
            promoter.promote(candidate)

    def test_already_promoted_candidate_raises_value_error(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        candidate = _make_validated_candidate(status=CandidateStatus.PROMOTED)

        with pytest.raises(ValueError, match="VALIDATED"):
            promoter.promote(candidate)

    def test_default_pending_status_raises_value_error(self):
        from src.pipeline.stages.candidate_promoter import CandidatePromoter

        promoter = CandidatePromoter()
        # Don't pass status — KnowledgeCandidate defaults to PENDING
        candidate = KnowledgeCandidate(
            id="cand-default",
            source_id="src-default",
            type=KnowledgeType.CONCEPT,
            title="Default Candidate",
            claims=[],
            confidence=0.5,
            evidence=[],
            raw_llm_output={},
        )

        assert candidate.status == CandidateStatus.PENDING
        with pytest.raises(ValueError, match="VALIDATED"):
            promoter.promote(candidate)
