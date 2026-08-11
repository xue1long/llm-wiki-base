"""Tests for src/pipeline/stages/reviewer.py — ReviewerStage rule engine."""
from pathlib import Path


from src.knowledge.core.candidate import KnowledgeCandidate
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


class TestEvidenceRefNormalization:
    """1-indexed evidence_refs are auto-normalized to 0-indexed before checks."""

    def test_1indexed_refs_normalized_and_pass(self, tmp_path):
        """When all refs >= 1 and max == evidence_count, subtract 1 from each."""
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        # evidence_count=6, refs in [1,6] → 1-indexed pattern
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[
                {"text": "Claim A", "evidence_refs": [1, 2]},
                {"text": "Claim B", "evidence_refs": [6]},  # max=6 == evidence_count
            ],
            evidence=[
                {"source_path": str(tmp_path / "e0.pdf"), "quote": "q0"},
                {"source_path": str(tmp_path / "e1.pdf"), "quote": "q1"},
                {"source_path": str(tmp_path / "e2.pdf"), "quote": "q2"},
                {"source_path": str(tmp_path / "e3.pdf"), "quote": "q3"},
                {"source_path": str(tmp_path / "e4.pdf"), "quote": "q4"},
                {"source_path": str(tmp_path / "e5.pdf"), "quote": "q5"},
            ],
        )
        for ev in candidate.evidence:
            Path(ev["source_path"]).write_text("x")

        result = stage.review(candidate, tmp_path)
        assert result.status == "validated", f"Expected validated, got {result.status}: {result.reason}"
        assert "evidence_existence" in result.checks_passed

    def test_0indexed_refs_untouched(self, tmp_path):
        """Already-correct 0-indexed refs are not modified."""
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[{"text": "Claim A", "evidence_refs": [0, 1]}],
        )
        result = stage.review(candidate, tmp_path)
        assert result.status == "validated"
        assert candidate.claims[0]["evidence_refs"] == [0, 1]

    def test_mixed_0_and_max_ref_not_normalized(self, tmp_path):
        """Mixed refs containing 0 AND evidence_count are genuinely malformed."""
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[{"text": "Bad mix", "evidence_refs": [0, 2]}],
            evidence=[
                {"source_path": str(tmp_path / "e0.pdf"), "quote": "q0"},
                {"source_path": str(tmp_path / "e1.pdf"), "quote": "q1"},
            ],
        )
        for ev in candidate.evidence:
            Path(ev["source_path"]).write_text("x")

        result = stage.review(candidate, tmp_path)
        assert result.status == "rejected"
        assert "evidence_existence" in result.checks_failed

    def test_stress_test_round1_pattern(self, tmp_path):
        """Reproduce: evidence_count=6, ref=6 → normalized to ref=5."""
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[
                {"text": "Claim 10 with OOB ref", "evidence_refs": [6]},
            ],
            evidence=[
                {"source_path": str(tmp_path / "e0.pdf"), "quote": "q0"},
                {"source_path": str(tmp_path / "e1.pdf"), "quote": "q1"},
                {"source_path": str(tmp_path / "e2.pdf"), "quote": "q2"},
                {"source_path": str(tmp_path / "e3.pdf"), "quote": "q3"},
                {"source_path": str(tmp_path / "e4.pdf"), "quote": "q4"},
                {"source_path": str(tmp_path / "e5.pdf"), "quote": "q5"},
            ],
        )
        for ev in candidate.evidence:
            Path(ev["source_path"]).write_text("x")

        result = stage.review(candidate, tmp_path)
        assert result.status == "validated"
        # ref was normalized from 6 to 5
        assert candidate.claims[0]["evidence_refs"] == [5]

    def test_all_refs_equal_evidence_count(self, tmp_path):
        """All refs == evidence_count (1-indexed last element)."""
        from src.pipeline.stages.reviewer import ReviewerStage

        stage = ReviewerStage()
        candidate = _make_valid_candidate(
            tmp_path,
            claims=[
                {"text": "C1", "evidence_refs": [3]},
                {"text": "C2", "evidence_refs": [3]},
            ],
            evidence=[
                {"source_path": str(tmp_path / "e0.pdf"), "quote": "q0"},
                {"source_path": str(tmp_path / "e1.pdf"), "quote": "q1"},
                {"source_path": str(tmp_path / "e2.pdf"), "quote": "q2"},
            ],
        )
        for ev in candidate.evidence:
            Path(ev["source_path"]).write_text("x")

        result = stage.review(candidate, tmp_path)
        assert result.status == "validated"
        assert candidate.claims[0]["evidence_refs"] == [2]
        assert candidate.claims[1]["evidence_refs"] == [2]


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
