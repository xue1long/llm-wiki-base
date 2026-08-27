"""Minimum Knowledge Compiler seam.

Public API:
    ClosureCheck, ClosureReport — spec §11.3 8 闭包条件 (B-3 commit 2)
    IntegrityGate, IntegrityReport, GateResult — 11 Gate 流水线 (B-3 commit 1)
    check_default_closure() — spec §11.3 8 条件 AND 校验 (B-3 commit 2)
    cmd_enable_closure, cmd_migrate_legacy — 30 天过渡期 CLI (B-3 commit 3)
"""
from .integrity.closure import (
    ClosureCheck,
    ClosureReport,
    check_default_closure,
)
from .integrity.orchestrator import (
    GateResult,
    IntegrityGate,
    IntegrityReport,
)

__all__ = [
    "ClosureCheck",
    "ClosureReport",
    "GateResult",
    "IntegrityGate",
    "IntegrityReport",
    "check_default_closure",
]
