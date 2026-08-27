"""Knowledge Integrity 11 Gates (B-2, spec §11.2).

Public API:
    Gate, GateVerdict, GateSeverity — 11 Gate 公共契约 (spec §11.2)
    SchemaGate     — Gate 1 (B-2.1 commit 1, 完整实现)
    ProvenanceGate — Gate 2 (B-2.1 commit 1 占位, commit 2 完整实现)
"""
from .gates import Gate, GateVerdict, GateSeverity, ProvenanceGate, SchemaGate

__all__ = [
    "Gate",
    "GateVerdict",
    "GateSeverity",
    "ProvenanceGate",
    "SchemaGate",
]