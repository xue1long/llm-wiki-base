"""System-owned evidence values produced from canonical source blocks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceBinding:
    evidence_id: str
    block_id: str
    quote: str
    quote_hash: str
    status: str = "structurally_verified"
    quote_truncated: bool = False
