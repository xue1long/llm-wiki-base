"""Knowledge candidate model — LLM-extracted claims awaiting review.

A KnowledgeCandidate wraps raw LLM output as opaque dicts (claims + evidence)
so ClaimParser / Reviewer / CandidatePromoter can operate in later phases
without re-running the extraction step.

Transition rules:
  PENDING -> VALIDATED   (Reviewer approves)
  PENDING -> REJECTED    (Reviewer rejects)
  VALIDATED -> PROMOTED  (CandidatePromoter creates KnowledgeObject)
  REJECTED -> PENDING    (re-review)
  PROMOTED is terminal
"""
from dataclasses import dataclass, field
from enum import Enum

from src.knowledge.core.object import KnowledgeType


class CandidateStatus(str, Enum):
    """4-state lifecycle for knowledge candidates."""

    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    PROMOTED = "promoted"


# Allowed transitions: from -> {to}
_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.PENDING: {CandidateStatus.VALIDATED, CandidateStatus.REJECTED},
    CandidateStatus.VALIDATED: {CandidateStatus.PROMOTED},
    CandidateStatus.REJECTED: {CandidateStatus.PENDING},
    CandidateStatus.PROMOTED: set(),  # terminal
}


def can_transition(from_status: CandidateStatus, to_status: CandidateStatus) -> bool:
    """Return True if transitioning from `from_status` to `to_status` is valid."""
    return to_status in _TRANSITIONS.get(from_status, set())


@dataclass
class KnowledgeCandidate:
    """Opaque candidate produced by LLM extraction, pending review.

    Claims and evidence are stored as opaque dicts. Structured Claim objects
    are introduced in Phase 2 (ClaimParser).

    evidence_refs in each claim dict are integer indices into the `evidence`
    list, associating claims with their supporting evidence.
    """

    id: str
    source_id: str
    type: KnowledgeType
    title: str
    claims: list[dict]
    confidence: float
    evidence: list[dict]
    raw_llm_output: dict
    status: CandidateStatus = field(default=CandidateStatus.PENDING)
    chunk_index: int | None = None
    chunk_total: int | None = None
    custom_type: str = ""
