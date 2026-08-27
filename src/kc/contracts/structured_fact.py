"""Structured Fact contract (路线 v2.2 §C-4.5 / Z-8, spec §5.6 + §3.5 P-5).

StructuredFact is the parameter-table / regulation / code-definition extraction
path that coexists with Claim (spec §3.5 "Claim 不是强制中间态"). Both paths
share Evidence + Context + Temporal + Integrity contracts.

identity_key algorithm (spec §5 table):
    identity_key = "id-v1:" + sha256({
        "subject", "field", "value", "value_type",
        "context_id", "validity_id"
    })
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


# Allowed value types (spec §5.6 schema).
ValueType = str  # "string" | "number" | "boolean" | "object" | "array"

# Allowed status lifecycle (spec §5.6 schema).
Status = str  # "candidate" | "verified" | "stale" | "rejected" | "quarantined"


@dataclass(frozen=True)
class StructuredFact:
    """Structured Fact (spec §5.6). Frozen dataclass — identity is field-derived.

    Fields:
        subject          "user.email" — dotted path identifying the entity.
        field            "value" — sub-field within the entity.
        value            string | number | bool | object | array payload.
        value_type       One of: string | number | boolean | object | array.
        context_id       Optional context scope (None = global).
        validity_id      Optional validity window (None = eternal).
        confidence       Extractor confidence in [0.0, 1.0].
        evidence_ids     Tuple of Evidence.evidence_id strings (shared,
                         not duplicated — spec §3.5).
        extraction_run_id  Identifies the run that produced this fact.
        status           Lifecycle (candidate | verified | stale | rejected | quarantined).
        version          Schema version counter.
        created_at       Unix ms when minted.
        updated_at       Unix ms when last mutated.
    """
    subject: str
    field: str
    value: Any
    value_type: str
    context_id: str | None
    validity_id: str | None
    confidence: float
    evidence_ids: tuple[str, ...]
    extraction_run_id: str
    status: str = "candidate"
    version: int = 1
    created_at: int = 0
    updated_at: int = 0


def compute_structured_fact_identity_key(sf: StructuredFact) -> str:
    """Deterministic id-v1 identity key (spec §5 table).

    Hashes the six identity-bearing fields in a stable, order-independent way
    so that the same StructuredFact yields the same key across processes.
    """
    payload = {
        "subject": sf.subject,
        "field": sf.field,
        "value": sf.value,
        "value_type": sf.value_type,
        "context_id": sf.context_id,
        "validity_id": sf.validity_id,
    }
    # Canonical JSON without spaces + UTF-8 + sha256.
    import json
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"id-v1:{digest}"


def evidence_for_field(
    *,
    document_id: str,
    block_id: str,
    field_signature: str,
    supports: tuple[str, ...],
):
    """Convenience factory that wraps ``evidence_for_quote`` using the
    field signature as the quote text. Useful when extracting Structured Facts
    from parameter tables where the "quote" is a field path + value tuple.
    """
    from src.kc.contracts.evidence import evidence_for_quote  # noqa: WPS433

    return evidence_for_quote(
        document_id=document_id,
        block_id=block_id,
        quote=field_signature,
        supports=supports,
    )