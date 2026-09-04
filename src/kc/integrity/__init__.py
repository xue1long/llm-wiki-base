"""Knowledge Integrity 11 Gates (B-2, spec §11.2) + Orchestrator (B-3).

Public API:
    Gate, GateVerdict, GateSeverity — 11 Gate 公共契约 (spec §11.2)
    SchemaGate     — Gate 1 (B-2.1 commit 1, 完整实现)
    ProvenanceGate — Gate 2 (B-2.1 commit 1 占位, commit 2 完整实现)
    EvidenceGate   — Gate 3 (B-2.2, 完整实现 + B-1 SemanticSupport 集成)
    IntegrityGate  — 11 Gate 流水线 orchestrator (B-3 commit 1, spec §11.2)
"""
from .gates import (
    EvidenceGate,
    Gate,
    GateSeverity,
    GateVerdict,
    ProvenanceGate,
    SchemaGate,
)
from .orchestrator import (
    GateResult,
    IntegrityGate,
    IntegrityReport,
)

__all__ = [
    "EvidenceGate",
    "Gate",
    "GateResult",
    "GateSeverity",
    "GateVerdict",
    "IntegrityGate",
    "IntegrityReport",
    "ProvenanceGate",
    "SchemaGate",
]
