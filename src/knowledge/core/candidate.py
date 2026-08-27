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

C-4 / G5 (路线 v2.2 §C-4 + K-2 加固) 新增 2 个 back-compat 默认字段：

* ``knowledge_mode`` — Observed/Synthesized/Unknown 标签（spec §7）
* ``failure_reason`` — 截断/失败原因（K-2 加固 5 场景 fail-closed）

既有字段全部不动；新增字段默认值保证 C-0 ~ C-3 既有调用方零回归。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

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
    # C-4 / G5: Observed/Synthesized/Unknown mode tag (spec §7).
    # Default "unknown" = fail-closed sentinel for K-2 truncation handling.
    knowledge_mode: Literal["observed", "synthesized", "unknown"] = "unknown"
    failure_reason: str | None = None
