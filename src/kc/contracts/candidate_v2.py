"""LLM-facing candidate contract for deterministic evidence binding."""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_binding import EvidenceBinding


@dataclass(frozen=True)
class ClaimV2:
    statement: str
    confidence: float
    evidence_block_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateV2:
    source_id: str
    type: str
    title: str
    claims: tuple[ClaimV2, ...]


@dataclass(frozen=True)
class BoundClaim:
    statement: str
    confidence: float
    evidence: tuple[EvidenceBinding, ...]


@dataclass(frozen=True)
class RejectedClaim:
    statement: str
    reason_code: str
    block_ids: tuple[str, ...]


@dataclass(frozen=True)
class AdaptationResult:
    candidate_v2: CandidateV2
    payload: dict
    generator_candidate: object
    rejected_claims: tuple[RejectedClaim, ...]
    valid_claim_count: int
    contract_version: str = "v2"
