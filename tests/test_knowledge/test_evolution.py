"""Tests for EvolutionLoop — Curator→Reviewer→Historian orchestration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.agent.curator import CuratorProposal
from src.knowledge.evolution import EvolutionConfig, EvolutionLoop, EvolutionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_proposal() -> CuratorProposal:
    """A valid CuratorProposal for testing."""
    return CuratorProposal(
        id="prop_test_improve_1234567890000",
        object_id="test-object",
        action="improve",
        before_snapshot={"title": "Test", "body": "before content", "grade": "C", "heat": 5},
        after_snapshot={"title": "Test", "body": "after content", "grade": "B", "heat": 5},
        diff="Grade C→B",
        reason="Low quality page needs improvement",
        confidence=0.8,
        proposed_at=1234567890000,
    )


@pytest.fixture
def invalid_proposal() -> CuratorProposal:
    """An invalid CuratorProposal (empty fields, low confidence)."""
    return CuratorProposal(
        id="",
        object_id="",
        action="improve",
        before_snapshot={},
        after_snapshot={},
        diff="",
        reason="",
        confidence=0.0,
        proposed_at=0,
    )


@pytest.fixture
def mock_curator(sample_proposal, invalid_proposal):
    """Mock CuratorAgent that returns proposals via curate()."""
    curator = MagicMock()
    curator.curate.return_value = [sample_proposal, invalid_proposal]
    curator.apply_proposal.return_value = True
    return curator


@pytest.fixture
def approving_reviewer():
    """A reviewer that approves every proposal."""
    reviewer = MagicMock()
    reviewer.validate.return_value = True
    return reviewer


@pytest.fixture
def rejecting_reviewer():
    """A reviewer that rejects every proposal."""
    reviewer = MagicMock()
    reviewer.validate.return_value = False
    return reviewer


@pytest.fixture
def selective_reviewer():
    """A reviewer that approves only proposals with confidence >= 0.5."""
    reviewer = MagicMock()
    reviewer.validate.side_effect = lambda p: p.confidence >= 0.5
    return reviewer


@pytest.fixture
def mock_historian():
    """Mock HistorianAgent for change recording."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: EvolutionConfig
# ---------------------------------------------------------------------------


class TestEvolutionConfigDefaults:
    """Safety-first defaults: auto_apply=False, dry_run=True."""

    def test_auto_apply_defaults_false(self):
        cfg = EvolutionConfig()
        assert cfg.auto_apply is False

    def test_dry_run_defaults_true(self):
        cfg = EvolutionConfig()
        assert cfg.dry_run is True

    def test_reviewer_validation_required_defaults_true(self):
        cfg = EvolutionConfig()
        assert cfg.reviewer_validation_required is True

    def test_max_objects_per_run_default(self):
        cfg = EvolutionConfig()
        assert cfg.max_objects_per_run == 100

    def test_safety_defaults_together(self):
        """Config is safe by default: no auto-apply, dry run on, validation required."""
        cfg = EvolutionConfig()
        assert cfg.auto_apply is False
        assert cfg.dry_run is True
        assert cfg.reviewer_validation_required is True


# ---------------------------------------------------------------------------
# Tests: EvolutionResult
# ---------------------------------------------------------------------------


class TestEvolutionResultDataclass:
    """All fields present and correct."""

    def test_default_fields(self):
        result = EvolutionResult(
            run_at=1000,
            proposals_generated=0,
            proposals_approved=0,
            proposals_applied=0,
            proposals_rejected=0,
            proposals_skipped=0,
        )
        assert result.run_at == 1000
        assert result.proposals_generated == 0
        assert result.errors == []
        assert result.duration_ms == 0

    def test_with_counts(self):
        result = EvolutionResult(
            run_at=2000,
            proposals_generated=10,
            proposals_approved=7,
            proposals_applied=5,
            proposals_rejected=2,
            proposals_skipped=2,
            errors=["error_1"],
            duration_ms=150,
        )
        assert result.proposals_generated == 10
        assert result.proposals_approved == 7
        assert result.proposals_applied == 5
        assert result.proposals_rejected == 2
        assert result.proposals_skipped == 2
        assert result.errors == ["error_1"]
        assert result.duration_ms == 150


# ---------------------------------------------------------------------------
# Tests: EvolutionLoop.run()
# ---------------------------------------------------------------------------


class TestRunEmpty:
    """No curator → empty EvolutionResult."""

    @pytest.mark.asyncio
    async def test_no_curator_returns_empty_result(self):
        loop = EvolutionLoop(curator=None)
        result = await loop.run()
        assert result.proposals_generated == 0
        assert result.proposals_approved == 0
        assert result.proposals_applied == 0
        assert result.proposals_rejected == 0
        assert result.proposals_skipped == 0


class TestRunDryRunMode:
    """Curator in dry_run mode → proposals generated but not applied."""

    @pytest.mark.asyncio
    async def test_dry_run_generates_proposals_not_applied(self, mock_curator):
        config = EvolutionConfig(dry_run=True, auto_apply=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)
        result = await loop.run()

        assert result.proposals_generated == 2
        # No reviewer, proposals auto-approved; auto_apply=False → all skipped
        assert result.proposals_applied == 0
        assert result.proposals_skipped == 2


class TestRunGeneratesProposals:
    """Curator returns proposals → EvolutionResult.proposals_generated > 0."""

    @pytest.mark.asyncio
    async def test_proposals_generated_gt_zero(self, mock_curator):
        loop = EvolutionLoop(curator=mock_curator)
        result = await loop.run()
        assert result.proposals_generated == 2


class TestRunReviewerApproves:
    """Valid proposal → reviewer approves → proposals_approved incremented."""

    @pytest.mark.asyncio
    async def test_reviewer_approves_valid_proposal(self, mock_curator, approving_reviewer):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p1", object_id="obj1", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.9, proposed_at=1,
            )
        ]
        config = EvolutionConfig(reviewer_validation_required=True, auto_apply=False)
        loop = EvolutionLoop(curator=mock_curator, reviewer=approving_reviewer, config=config)
        result = await loop.run()
        assert result.proposals_approved == 1
        assert result.proposals_rejected == 0


class TestRunReviewerRejects:
    """Invalid proposal → proposals_rejected incremented."""

    @pytest.mark.asyncio
    async def test_reviewer_rejects_invalid_proposal(self, mock_curator, rejecting_reviewer):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p2", object_id="obj2", action="improve",
                before_snapshot={}, after_snapshot={},
                diff="", reason="", confidence=0.0, proposed_at=1,
            )
        ]
        config = EvolutionConfig(reviewer_validation_required=True, auto_apply=False)
        loop = EvolutionLoop(curator=mock_curator, reviewer=rejecting_reviewer, config=config)
        result = await loop.run()
        assert result.proposals_rejected == 1
        assert result.proposals_approved == 0


class TestAutoApplyTrue:
    """auto_apply=True, approved → proposals_applied incremented."""

    @pytest.mark.asyncio
    async def test_auto_apply_true_applies_approved(self, mock_curator):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p3", object_id="obj3", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.9, proposed_at=1,
            )
        ]
        mock_curator.apply_proposal.return_value = True
        config = EvolutionConfig(auto_apply=True, reviewer_validation_required=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)
        result = await loop.run()
        assert result.proposals_applied == 1
        assert result.proposals_skipped == 0
        mock_curator.apply_proposal.assert_called_once_with("p3")


class TestAutoApplyFalse:
    """auto_apply=False → proposals_skipped incremented (even if approved)."""

    @pytest.mark.asyncio
    async def test_auto_apply_false_skips_all(self, mock_curator):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p4", object_id="obj4", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.9, proposed_at=1,
            )
        ]
        config = EvolutionConfig(auto_apply=False, reviewer_validation_required=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)
        result = await loop.run()
        assert result.proposals_skipped == 1
        assert result.proposals_applied == 0
        mock_curator.apply_proposal.assert_not_called()


class TestHistorianRecords:
    """Historian available → each action recorded."""

    @pytest.mark.asyncio
    async def test_historian_records_applied(self, mock_curator, mock_historian):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p5", object_id="obj5", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="test reason", confidence=0.9, proposed_at=1,
            )
        ]
        mock_curator.apply_proposal.return_value = True
        config = EvolutionConfig(auto_apply=True, reviewer_validation_required=False)
        loop = EvolutionLoop(
            curator=mock_curator, historian=mock_historian, config=config,
        )
        await loop.run()
        mock_historian.record_change.assert_called_once()
        call_kwargs = mock_historian.record_change.call_args[1]
        assert call_kwargs["object_id"] == "obj5"
        assert "applied" in str(call_kwargs["change_type"])

    @pytest.mark.asyncio
    async def test_historian_records_skipped(self, mock_curator, mock_historian):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p6", object_id="obj6", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="test reason", confidence=0.9, proposed_at=1,
            )
        ]
        config = EvolutionConfig(auto_apply=False, reviewer_validation_required=False)
        loop = EvolutionLoop(
            curator=mock_curator, historian=mock_historian, config=config,
        )
        await loop.run()
        mock_historian.record_change.assert_called_once()
        call_kwargs = mock_historian.record_change.call_args[1]
        assert "skipped" in str(call_kwargs["change_type"])

    @pytest.mark.asyncio
    async def test_historian_records_rejected(self, mock_curator, mock_historian, rejecting_reviewer):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p7", object_id="obj7", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="test reason", confidence=0.9, proposed_at=1,
            )
        ]
        config = EvolutionConfig(reviewer_validation_required=True, auto_apply=False)
        loop = EvolutionLoop(
            curator=mock_curator, reviewer=rejecting_reviewer,
            historian=mock_historian, config=config,
        )
        await loop.run()
        mock_historian.record_change.assert_called_once()
        call_kwargs = mock_historian.record_change.call_args[1]
        assert "rejected" in str(call_kwargs["change_type"])


class TestRunCountIncrements:
    """Two runs → run_count=2."""

    @pytest.mark.asyncio
    async def test_run_count_increments(self, mock_curator):
        loop = EvolutionLoop(curator=mock_curator)
        assert loop._run_count == 0
        await loop.run()
        assert loop._run_count == 1
        await loop.run()
        assert loop._run_count == 2


class TestGetStatus:
    """get_status returns run_count, last_run_at, config."""

    @pytest.mark.asyncio
    async def test_get_status_defaults(self):
        loop = EvolutionLoop()
        status = loop.get_status()
        assert status["run_count"] == 0
        assert status["last_run_at"] == 0
        assert status["config"]["auto_apply"] is False
        assert status["config"]["dry_run"] is True

    @pytest.mark.asyncio
    async def test_get_status_after_run(self, mock_curator):
        loop = EvolutionLoop(curator=mock_curator)
        await loop.run()
        status = loop.get_status()
        assert status["run_count"] == 1
        assert status["last_run_at"] > 0


class TestMultipleProposalsMixedResults:
    """Some approved, some rejected, some skipped → correct counts."""

    @pytest.mark.asyncio
    async def test_mixed_results(self, mock_curator, selective_reviewer):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="high_conf", object_id="obj_a", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.8, proposed_at=1,
            ),
            CuratorProposal(
                id="low_conf", object_id="obj_b", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.2, proposed_at=2,
            ),
        ]
        mock_curator.apply_proposal.return_value = True
        config = EvolutionConfig(reviewer_validation_required=True, auto_apply=False)
        loop = EvolutionLoop(
            curator=mock_curator, reviewer=selective_reviewer, config=config,
        )
        result = await loop.run()
        assert result.proposals_generated == 2
        assert result.proposals_approved == 1   # high_conf approved
        assert result.proposals_rejected == 1   # low_conf rejected
        assert result.proposals_skipped == 1    # high_conf skipped (auto_apply=False)


class TestGracefulDegradationNoReviewer:
    """No reviewer → proposals approved by default."""

    @pytest.mark.asyncio
    async def test_no_reviewer_auto_approves(self, mock_curator):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p8", object_id="obj8", action="improve",
                before_snapshot={}, after_snapshot={},
                diff="", reason="", confidence=0.0, proposed_at=1,
            )
        ]
        config = EvolutionConfig(reviewer_validation_required=True, auto_apply=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)  # no reviewer
        result = await loop.run()
        assert result.proposals_approved == 1
        assert result.proposals_rejected == 0


class TestGracefulDegradationNoHistorian:
    """No historian → no crash, no history recorded."""

    @pytest.mark.asyncio
    async def test_no_historian_no_crash(self, mock_curator):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p9", object_id="obj9", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.9, proposed_at=1,
            )
        ]
        config = EvolutionConfig(auto_apply=True, reviewer_validation_required=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)  # no historian
        result = await loop.run()
        # No crash and results still computed
        assert result.proposals_generated == 1
        assert result.proposals_applied == 1


class TestErrorsCaptured:
    """Exception during proposal handling → captured in errors list."""

    @pytest.mark.asyncio
    async def test_apply_failure_captured(self, mock_curator):
        mock_curator.curate.return_value = [
            CuratorProposal(
                id="p10", object_id="obj10", action="improve",
                before_snapshot={"x": 1}, after_snapshot={"x": 2},
                diff="d", reason="r", confidence=0.9, proposed_at=1,
            )
        ]
        mock_curator.apply_proposal.side_effect = RuntimeError("apply exploded")
        config = EvolutionConfig(auto_apply=True, reviewer_validation_required=False)
        loop = EvolutionLoop(curator=mock_curator, config=config)
        result = await loop.run()
        assert len(result.errors) == 1
        assert "apply exploded" in result.errors[0]
        assert result.proposals_skipped == 1


# ---------------------------------------------------------------------------
# Tests: _builtin_validate
# ---------------------------------------------------------------------------


class TestBuiltinValidate:
    """The built-in validation heuristic for CuratorProposals."""

    def test_valid_proposal_passes(self, sample_proposal):
        assert EvolutionLoop._builtin_validate(sample_proposal) is True

    def test_empty_id_fails(self, sample_proposal):
        sample_proposal.id = ""
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_empty_object_id_fails(self, sample_proposal):
        sample_proposal.object_id = ""
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_empty_before_snapshot_fails(self, sample_proposal):
        sample_proposal.before_snapshot = {}
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_empty_after_snapshot_fails(self, sample_proposal):
        sample_proposal.after_snapshot = {}
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_empty_reason_fails(self, sample_proposal):
        sample_proposal.reason = ""
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_low_confidence_fails(self, sample_proposal):
        sample_proposal.confidence = 0.2
        assert EvolutionLoop._builtin_validate(sample_proposal) is False

    def test_confidence_at_threshold_passes(self, sample_proposal):
        sample_proposal.confidence = 0.3
        assert EvolutionLoop._builtin_validate(sample_proposal) is True
