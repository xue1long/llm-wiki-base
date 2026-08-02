"""EvolutionLoop — orchestrates periodic self-improvement cycles.

Flow: Curator → Reviewer → (auto-apply) → Historian

This module does NOT reimplement Curator, Reviewer, or Historian logic.
It delegates to those agents and coordinates the pipeline.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agent.curator import CuratorAgent, CuratorProposal
    from src.agent.historian import HistorianAgent

_logger = logging.getLogger(__name__)


@dataclass
class EvolutionConfig:
    """Configuration for an EvolutionLoop.

    Safety-first defaults:
    - auto_apply=False: proposals are never applied without explicit opt-in
    - dry_run=True: curator only reports, no on-disk proposals
    - reviewer_validation_required=True: proposals must pass validation
    """

    max_objects_per_run: int = 100
    auto_apply: bool = False
    dry_run: bool = True
    reviewer_validation_required: bool = True


@dataclass
class EvolutionResult:
    """Summary of one evolution cycle run."""

    run_at: int                    # Unix ms
    proposals_generated: int       # Total proposals from Curator
    proposals_approved: int        # Number that passed Reviewer
    proposals_applied: int         # Number actually applied (only if auto_apply)
    proposals_rejected: int        # Number rejected by Reviewer
    proposals_skipped: int         # Not applied (auto_apply false, or other reasons)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0           # How long the cycle took


class EvolutionLoop:
    """Orchestrates periodic self-improvement.

    Flow:
    1. Curator reviews knowledge → generates CuratorProposals
    2. Reviewer validates each proposal
    3. If auto_apply enabled AND proposal approved → apply
    4. Historian records all changes

    This is the high-level orchestrator. It does NOT reimplement
    Curator, Reviewer, or Historian logic — it delegates.
    """

    def __init__(
        self,
        curator: CuratorAgent | None = None,
        reviewer: Any = None,
        historian: HistorianAgent | None = None,
        config: EvolutionConfig | None = None,
    ) -> None:
        self.curator = curator
        self.reviewer = reviewer
        self.historian = historian
        self.config = config or EvolutionConfig()
        self._run_count: int = 0
        self._last_run_at: int = 0

    # -- Public API -------------------------------------------------------

    async def run(self) -> EvolutionResult:
        """Run one full evolution cycle.

        1. Curator.curate() → proposals
        2. For each proposal:
           a. If reviewer available → validate
           b. If approved AND auto_apply → Curator.apply_proposal()
           c. Historian.record_change() for each action
        3. Return EvolutionResult with summary
        """
        start_time = int(time.time() * 1000)
        errors: list[str] = []

        # Graceful degradation: no curator means nothing to do
        if self.curator is None:
            return EvolutionResult(
                run_at=start_time,
                proposals_generated=0,
                proposals_approved=0,
                proposals_applied=0,
                proposals_rejected=0,
                proposals_skipped=0,
                errors=[],
                duration_ms=0,
            )

        proposals = self.curator.curate()

        proposals_generated = len(proposals)
        approved = 0
        applied = 0
        rejected = 0
        skipped = 0

        for proposal in proposals:
            try:
                # ---- Step 2a: validate ----
                is_approved = self._check_approval(proposal)

                if is_approved:
                    approved += 1
                else:
                    rejected += 1
                    self._record_action(proposal, "rejected")
                    continue

                # ---- Step 2b: apply or skip ----
                if self.config.auto_apply:
                    try:
                        ok = self.curator.apply_proposal(proposal.id)
                        if ok:
                            applied += 1
                            self._record_action(proposal, "applied")
                        else:
                            skipped += 1
                            self._record_action(proposal, "apply_failed")
                    except Exception as exc:
                        msg = f"Failed to apply proposal {proposal.id}: {exc}"
                        _logger.warning(msg)
                        errors.append(msg)
                        skipped += 1
                        self._record_action(proposal, "apply_failed")
                else:
                    skipped += 1
                    self._record_action(proposal, "skipped")

            except Exception as exc:
                msg = f"Error processing proposal {proposal.id}: {exc}"
                _logger.exception(msg)
                errors.append(msg)

        end_time = int(time.time() * 1000)
        self._run_count += 1
        self._last_run_at = end_time

        return EvolutionResult(
            run_at=start_time,
            proposals_generated=proposals_generated,
            proposals_approved=approved,
            proposals_applied=applied,
            proposals_rejected=rejected,
            proposals_skipped=skipped,
            errors=errors,
            duration_ms=end_time - start_time,
        )

    def get_status(self) -> dict[str, Any]:
        """Return evolution loop status: {run_count, last_run_at, config}."""
        return {
            "run_count": self._run_count,
            "last_run_at": self._last_run_at,
            "config": {
                "max_objects_per_run": self.config.max_objects_per_run,
                "auto_apply": self.config.auto_apply,
                "dry_run": self.config.dry_run,
                "reviewer_validation_required": self.config.reviewer_validation_required,
            },
        }

    # -- Internal helpers -------------------------------------------------

    def _check_approval(self, proposal: CuratorProposal) -> bool:
        """Determine whether a proposal passes validation.

        Logic:
        - If reviewer_validation_required is False → auto-approve
        - If reviewer is None → auto-approve (graceful degradation)
        - If reviewer has a ``validate`` method → delegate to it
        - Otherwise → fall back to built-in heuristic
        """
        if not self.config.reviewer_validation_required:
            return True

        if self.reviewer is None:
            return True

        # Delegate to reviewer if it has a validate method
        if hasattr(self.reviewer, "validate") and callable(self.reviewer.validate):
            return bool(self.reviewer.validate(proposal))

        # Built-in heuristic fallback
        return self._builtin_validate(proposal)

    @staticmethod
    def _builtin_validate(proposal: CuratorProposal) -> bool:
        """Basic validation checks for a CuratorProposal.

        Returns True when:
        - Proposal has a valid ID and object_id
        - before_snapshot and after_snapshot are non-empty
        - reason is non-empty
        - confidence >= 0.3
        """
        return (
            bool(proposal.id)
            and bool(proposal.object_id)
            and bool(proposal.before_snapshot)
            and bool(proposal.after_snapshot)
            and bool(proposal.reason)
            and proposal.confidence >= 0.3
        )

    def _record_action(self, proposal: CuratorProposal, action: str) -> None:
        """Record an evolution action via the Historian, if available."""
        if self.historian is None:
            return
        try:
            self.historian.record_change(
                object_id=proposal.object_id,
                change_type=f"evolution_{action}",
                reason=proposal.reason,
                agent="evolution_loop",
            )
        except Exception:
            _logger.debug(
                "Historian record failed for proposal %s action %s",
                proposal.id, action, exc_info=True,
            )
