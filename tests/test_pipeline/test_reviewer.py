"""Tests for src/pipeline/stages/reviewer.py — ReviewerStage rule engine."""
import tempfile
from pathlib import Path

import pytest

from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType


# ---------------------------------------------------------------------------
# Helper: build a valid candidate that passes all checks
# ---------------------------------------------------------------------------
def _make_valid_candidate(tmp_dir: Path, **overrides) -> KnowledgeCandidate:
    evidence_file = tmp_dir / "source_001.pdf"
    evidence_file.write_text("dummy content")

    defaults = dict(
        id="cand-001",
        source_id="src-001",
        type=KnowledgeType.CONCEPT,
        title="Test Concept",
        claims=[
            {
                "text": "Claim A",
                "evidence_refs": [0, 1],
            },
            {
                "text": "Claim B",
                "evidence_refs": [1],
            },
        ],
        confidence=0.85,
        evidence=[
            {
                "source_path": str(evidence_file),
                "quote": "evidence quote A",
            },
            {
                "source_path": str(evidence_file),
                "quote": "evidence quote B",
            },
        ],
        raw_llm_output={"raw": "data"},
    )
    defaults.update(overrides)
    return KnowledgeCandidate(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestReviewerValidCandidate:
    """Candidate that passes all 4 checks -> VALIDATED."""

    def test_valid_candidate_passes_all_checks(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path)
        result = stage.review(candidate, tmp_path)

        assert result.status == "validated"
        assert len(result.checks_failed) == 0
        assert len(result.checks_passed) == 4
        assert "schema_compliance" in result.checks_passed
        assert "evidence_existence" in result.checks_passed
        assert "reference_consistency" in result.checks_passed
        assert "confidence_threshold" in result.checks_passed


class TestReviewerSchemaCompliance:
    """Check 1: required fields (id, source_id, type, title)."""

    def test_missing_source_id_rejected(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path, source_id="")
        result = stage.review(candidate, tmp_path)

        assert result.status == "rejected"
        assert "schema_compliance" in result.checks_failed
        assert "source_id" in result.reason.lower()


class TestReviewerEvidenceExistence:
    """Check 2: every claim must have at least 1 evidence_ref in bounds."""

    def test_claim_with_no_evidence_refs_rejected(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[{"text": "Claim with no evidence", "evidence_refs": []}],
        )
        result = stage.review(candidate, tmp_path)

        assert result.status == "rejected"
        assert "evidence_existence" in result.checks_failed

    def test_claim_with_out_of_bounds_evidence_ref_rejected(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[{"text": "Bad ref", "evidence_refs": [99]}],
        )
        result = stage.review(candidate, tmp_path)

        assert result.status == "rejected"
        assert "evidence_existence" in result.checks_failed


class TestReviewerReferenceConsistency:
    """Check 3: each evidence source_path must exist on filesystem."""

    def test_evidence_file_not_found_rejected(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            evidence=[
                {
                    "source_path": str(tmp_path / "nonexistent.pdf"),
                    "quote": "ghost evidence",
                },
            ],
        )
        result = stage.review(candidate, tmp_path)

        assert result.status == "rejected"
        assert "reference_consistency" in result.checks_failed


class TestReviewerConfidenceThreshold:
    """Check 4: confidence-based gating."""

    def test_confidence_0_3_rejected(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path, confidence=0.3)
        result = stage.review(candidate, tmp_path)

        assert result.status == "rejected"
        assert "confidence_threshold" in result.checks_failed

    def test_confidence_0_6_needs_human_review(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path, confidence=0.6)
        result = stage.review(candidate, tmp_path)

        assert result.status == "needs_human_review"
        assert "confidence_threshold" in result.checks_failed
        assert "between" in result.reason.lower()

    def test_confidence_0_9_validated(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path, confidence=0.9)
        result = stage.review(candidate, tmp_path)

        assert result.status == "validated"
        assert "confidence_threshold" in result.checks_passed


class TestReviewerIdempotency:
    """Same candidate_id reviewed twice -> same result."""

    def test_idempotency_same_result(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path)
        result1 = stage.review(candidate, tmp_path)
        result2 = stage.review(candidate, tmp_path)

        assert result1.status == result2.status
        assert result1.reason == result2.reason
        assert result1.checks_passed == result2.checks_passed
        assert result1.checks_failed == result2.checks_failed


class TestReviewerAllChecksTracked:
    """Verify that all 4 check names appear in checks_passed or checks_failed."""

    def test_all_four_checks_listed(self, tmp_path):
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(tmp_path)
        result = stage.review(candidate, tmp_path)

        all_checks = set(result.checks_passed) | set(result.checks_failed)
        expected = {"schema_compliance", "evidence_existence", "reference_consistency", "confidence_threshold"}
        assert all_checks == expected
