"""Evidence Strength Policy (路线 v2.2 §C-1 / G1, spec §6).

``StrengthPolicy.compute_strength(evidence)`` returns one of
``"strong" | "medium" | "weak"`` based on:

* the evidence's ``evidence_type`` (base strength table), then
* provenance-field completeness (demotion rules E-14, E-15).

The policy is intentionally side-effect-free and stateless so callers can
re-run it freely after editing provenance fields. ``strength`` is **never**
stored on the Evidence value object itself — it is derived.
"""
from __future__ import annotations

from .evidence import Evidence, EvidenceStrength


# Base strength per evidence_type (spec §6 default table).
_BASE_STRENGTH: dict[str, EvidenceStrength] = {
    "direct_quote": "strong",
    "structured_source": "strong",
    "code": "strong",
    "computed": "medium",
    "multi_source": "medium",
    "inferred": "weak",
}

# spec §6 E-15: structured_source missing schema_id/record_key/field_path → weak.
_STRUCTURED_REQUIRED = frozenset({"schema_id", "record_key", "field_path"})

# spec §6 E-14: computed missing input_ids/algorithm/algorithm_version/result_hash → weak.
_COMPUTATION_REQUIRED = frozenset({
    "input_ids", "algorithm", "algorithm_version", "result_hash",
})


class StrengthPolicy:
    """Compute Evidence strength from ``evidence_type`` + provenance fields."""

    def compute_strength(self, evidence: Evidence) -> EvidenceStrength:
        base = _BASE_STRENGTH.get(evidence.evidence_type, "medium")

        # spec §6 E-15
        if evidence.evidence_type == "structured_source":
            sp = evidence.structured_provenance or {}
            if not _STRUCTURED_REQUIRED.issubset(sp.keys()):
                return "weak"

        # spec §6 E-14
        if evidence.evidence_type == "computed":
            cp = evidence.computation_provenance or {}
            if not _COMPUTATION_REQUIRED.issubset(cp.keys()):
                return "weak"

        return base