"""Claim-level evidence model for Stage 5."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ClaimSupport(str, Enum):
    """Three orthogonal failure kinds live here — none of them is a technical
    failure (Failure Contract §1.3). A technical failure never produces a
    Claim at all."""

    SUPPORTED = "supported"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING = "conflicting"


class ClaimRisk(str, Enum):
    LOW = "low"
    HIGH = "high"   # numbers / negation / causality / comparison -> needs reviewer


_PLACEHOLDER = "需结合原文核对"


@dataclass(frozen=True)
class EvidenceRef:
    """Pointer to a byte range inside the ORIGINAL source bytes.

    start_byte/end_byte are SOURCE-ABSOLUTE UTF-8 byte offsets — slicing
    ``source_bytes[start_byte:end_byte]`` is correct with no arithmetic.
    """

    item_id: str
    item_index: int
    span_index: int
    start_byte: int
    end_byte: int

    def excerpt_from(self, source_bytes: bytes) -> str:
        """Deterministic excerpt — never trusts LLM-supplied text."""
        return source_bytes[self.start_byte:self.end_byte].decode("utf-8", errors="replace")


@dataclass
class Claim:
    claim_id: str
    slot_name: str
    text: str
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    support: ClaimSupport = ClaimSupport.INSUFFICIENT_EVIDENCE
    confidence: float = 0.0
    risk: ClaimRisk = ClaimRisk.LOW

    def is_substantive(self) -> bool:
        """True iff text has real content (not empty, not the legacy placeholder)."""
        stripped = self.text.strip()
        return bool(stripped) and stripped != _PLACEHOLDER


__all__ = [
    "Claim",
    "ClaimRisk",
    "ClaimSupport",
    "EvidenceRef",
]
