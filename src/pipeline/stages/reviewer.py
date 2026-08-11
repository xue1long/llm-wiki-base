"""ReviewerStage — pure rule engine (Phase 1).

Validates KnowledgeCandidate before promotion. Does NOT use LLM.
Does NOT detect hallucination. Phase 4 optionally upgrades to LLM-assisted
Reviewer.

Idempotency: cached by candidate.id with 1-hour TTL so the same candidate
reviewed twice returns the identical ReviewResult (including reason and
check lists).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ...events.event_bus import event_bus
from ...knowledge.core.candidate import CandidateStatus, KnowledgeCandidate


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class ReviewResult:
    candidate_id: str
    status: str          # VALIDATED | NEEDS_HUMAN_REVIEW | REJECTED
    reason: str          # human-readable reason
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Idempotency cache (in-process, 1-hour TTL)
# ---------------------------------------------------------------------------
_IDEMPOTENCY_TTL = 3600  # 1 hour


class _ReviewCache:
    def __init__(self):
        self._store: dict[str, tuple[float, ReviewResult]] = {}

    def get(self, candidate_id: str) -> ReviewResult | None:
        entry = self._store.get(candidate_id)
        if entry is None:
            return None
        ts, result = entry
        if time.time() - ts > _IDEMPOTENCY_TTL:
            del self._store[candidate_id]
            return None
        return result

    def put(self, candidate_id: str, result: ReviewResult) -> None:
        self._store[candidate_id] = (time.time(), result)


# ---------------------------------------------------------------------------
# ReviewerStage
# ---------------------------------------------------------------------------
class ReviewerStage:
    """Phase 1: Pure rule engine. Validates KnowledgeCandidate before promotion.

    Does NOT use LLM. Does NOT detect hallucination.
    Phase 4 optionally upgrades to LLM-assisted Reviewer.
    """

    # Permission gate (checked by Kernel before calling ReviewerStage)
    REQUIRED_PERMISSION = "candidate.approve"

    def __init__(self):
        self._cache = _ReviewCache()

    def review(self, candidate: KnowledgeCandidate, project_path: Path) -> ReviewResult:
        """Run 4 rule-based checks and return VALIDATED or REJECTED.

        Idempotent: same candidate.id within the TTL window returns the
        cached ReviewResult.
        """
        # --- Idempotency check ---
        cached = self._cache.get(candidate.id)
        if cached is not None:
            return cached

        # --- Normalize evidence_refs (1-indexed → 0-indexed) ---
        self._normalize_evidence_refs(candidate)

        # --- Run all checks ---
        passed: list[str] = []
        failed: list[str] = []
        reasons: list[str] = []

        # Check 1: Schema compliance
        self._check_schema(candidate, passed, failed, reasons)

        # Check 2: Evidence existence
        self._check_evidence(candidate, passed, failed, reasons)

        # Check 3: Reference consistency
        self._check_references(candidate, project_path, passed, failed, reasons)

        # Check 4: Confidence threshold
        confidence_status = self._check_confidence(candidate, passed, failed, reasons)

        # Determine final status: structural failures override confidence
        structural_failures = {"schema_compliance", "evidence_existence", "reference_consistency"}
        if structural_failures & set(failed):
            status = "rejected"
        else:
            status = confidence_status

        # Determine final reason
        if failed:
            reason = "; ".join(reasons)
        else:
            reason = "All checks passed"

        result = ReviewResult(
            candidate_id=candidate.id,
            status=status,
            reason=reason,
            checks_passed=passed,
            checks_failed=failed,
        )

        # --- Mutate candidate status ---
        # Map result status to CandidateStatus enum. "needs_human_review"
        # is not a CandidateStatus value — the candidate stays PENDING
        # until a human explicitly approves or rejects it.
        _status_map: dict[str, CandidateStatus] = {
            "validated": CandidateStatus.VALIDATED,
            "rejected": CandidateStatus.REJECTED,
            "needs_human_review": CandidateStatus.PENDING,
        }
        candidate.status = _status_map.get(status, CandidateStatus.REJECTED)

        # --- Cache for idempotency ---
        self._cache.put(candidate.id, result)

        # --- Emit event for downstream stages ---
        if status == "validated":
            event_bus.emit("candidate:validated", {
                "candidate": candidate,
                "result": result,
            })

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_evidence_refs(candidate: KnowledgeCandidate) -> None:
        """Detect and fix 1-indexed evidence_refs (LLM convention drift).

        When the LLM uses 1-indexed refs, every max ref equals evidence_count
        instead of evidence_count-1. This normalizes by subtracting 1 from all
        refs when the pattern is detected.

        Handles mixed-index cases: most claims 0-indexed but a few 1-indexed.
        """
        evidence_count = len(candidate.evidence)
        if evidence_count == 0:
            return
        all_refs = [
            r
            for claim in candidate.claims
            for r in claim.get("evidence_refs", [])
            if isinstance(r, int)
        ]
        if not all_refs:
            return
        max_ref = max(all_refs)
        min_ref = min(all_refs)
        # Pass 1: unambiguously 1-indexed — all refs >= 1 and max == evidence_count
        if min_ref >= 1 and max_ref == evidence_count:
            for claim in candidate.claims:
                refs = claim.get("evidence_refs", [])
                if refs:
                    claim["evidence_refs"] = [r - 1 for r in refs if isinstance(r, int)]

        # Pass 2: mixed-index — most claims 0-indexed, but some claims
        # independently 1-indexed.  Check each claim: if all its refs >= 1
        # and its max == evidence_count, treat it as 1-indexed and fix it.
        # Safe to run after Pass 1 because Pass 1 already zeroed all refs,
        # so `all(r >= 1)` won't match any claim that was already normalized.
        for claim in candidate.claims:
            refs = claim.get("evidence_refs", [])
            if not refs or not all(isinstance(r, int) for r in refs):
                continue
            if all(r >= 1 for r in refs) and max(refs) == evidence_count:
                claim["evidence_refs"] = [r - 1 for r in refs]

    @staticmethod
    def _check_schema(
        candidate: KnowledgeCandidate,
        passed: list[str],
        failed: list[str],
        reasons: list[str],
    ) -> None:
        required = {
            "id": candidate.id,
            "source_id": candidate.source_id,
            "type": candidate.type,
            "title": candidate.title,
        }
        missing = [field for field, value in required.items() if not value]
        if missing:
            failed.append("schema_compliance")
            reasons.append(f"Missing required fields: {', '.join(missing)}")
        else:
            passed.append("schema_compliance")

    @staticmethod
    def _check_evidence(
        candidate: KnowledgeCandidate,
        passed: list[str],
        failed: list[str],
        reasons: list[str],
    ) -> None:
        evidence_count = len(candidate.evidence)
        for i, claim in enumerate(candidate.claims):
            refs = claim.get("evidence_refs", [])
            if not refs:
                failed.append("evidence_existence")
                reasons.append(f"Claim {i} has no evidence_refs")
                return
            for ref in refs:
                if not isinstance(ref, int) or ref < 0 or ref >= evidence_count:
                    failed.append("evidence_existence")
                    reasons.append(
                        f"Claim {i} evidence_ref {ref} is out of bounds "
                        f"(evidence count: {evidence_count})"
                    )
                    return
        passed.append("evidence_existence")

    @staticmethod
    def _check_references(
        candidate: KnowledgeCandidate,
        project_path: Path,
        passed: list[str],
        failed: list[str],
        reasons: list[str],
    ) -> None:
        for i, ev in enumerate(candidate.evidence):
            source_path_str = ev.get("source_path", "")
            if not source_path_str:
                failed.append("reference_consistency")
                reasons.append(f"Evidence {i} has no source_path")
                return
            normalized = source_path_str.replace("\\", "/")
            file_path = project_path / normalized
            if not file_path.is_file():
                failed.append("reference_consistency")
                reasons.append(f"Evidence {i} source_path not found: {source_path_str}")
                return
        passed.append("reference_consistency")

    @staticmethod
    def _check_confidence(
        candidate: KnowledgeCandidate,
        passed: list[str],
        failed: list[str],
        reasons: list[str],
    ) -> str:
        c = candidate.confidence
        if c < 0.5:
            failed.append("confidence_threshold")
            reasons.append(f"Confidence {c} is below minimum threshold (0.5)")
            return "rejected"
        elif c < 0.7:
            failed.append("confidence_threshold")
            reasons.append(
                f"Confidence {c} is between 0.5 and 0.7 — needs human review"
            )
            return "needs_human_review"
        else:
            passed.append("confidence_threshold")
            return "validated"
