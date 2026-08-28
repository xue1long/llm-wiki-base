"""Evidence contract; source verification remains outside this value object.

Persistence layout (路线 v2.2 §C-1 / G1):
    .index/evidence/<evidence_id>.json

Each Evidence has a stable ``evidence_id`` (separate from ``quote_hash`` so
that the same quote may be referenced by multiple IDs when it backs different
claims, and so the id can be minted before the hash is computed).

Provenance fields (spec §5.7):
    structured_provenance   {schema_id, record_key, field_path}
    computation_provenance  {input_ids, algorithm, algorithm_version, result_hash}

Both default to ``None``; missing required keys drive StrengthPolicy demotion
(spec §6 E-14/E-15) instead of being silently treated as valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from src.kc.domain.ids import evidence_id as make_evidence_id


# ── type aliases (spec §5.7) ─────────────────────────────────────────────

EvidenceType = Literal[
    "direct_quote", "structured_source", "code", "computed",
    "multi_source", "inferred",
]

EvidenceStrength = Literal["strong", "medium", "weak"]


@dataclass(frozen=True)
class Evidence:
    # C-1: stable identifier for .index/evidence/<evidence_id>.json.
    evidence_id: str = ""
    document_id: str = ""
    block_id: str = ""
    quote: str = ""
    quote_hash: str = ""
    # Made optional with ``()`` default for backward-compat with the four
    # historical call sites that always passed a tuple explicitly.
    supports: tuple[str, ...] = ()
    confidence: float = 0.0
    status: str = "candidate"
    # spec §5.7 provenance fields. ``None`` means "absent"; StrengthPolicy
    # demotes when required keys are missing.
    evidence_type: str = "direct_quote"
    structured_provenance: dict | None = None
    computation_provenance: dict | None = None


def evidence_for_quote(
    *, document_id: str, block_id: str, quote: str, supports: tuple[str, ...]
) -> Evidence:
    """Create a candidate Evidence value with a deterministic quote hash."""
    return Evidence(
        evidence_id=make_evidence_id(
            document_id,
            block_id,
            sha256(quote.encode("utf-8")).hexdigest(),
            tuple(supports),
        ),
        document_id=document_id,
        block_id=block_id,
        quote=quote,
        quote_hash=sha256(quote.encode("utf-8")).hexdigest(),
        supports=tuple(supports),
    )
