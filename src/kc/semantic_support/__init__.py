"""Semantic Support Check (B-1, spec §6 末段 + §11.4 #9 + §A2 Gate).

Roadmap v2.2 §B-1 — release-time semantic support check.

Public API::

    from src.kc.semantic_support import (
        SemanticSupportChecker,
        SupportVerdict,
        SupportType,
    )

Design decisions (路线 v2.2):
    H-3: ON by default — interface accepts ``llm_provider``.
    H-6: 50 元/日成本上限 + 抽样 1/10 (``sample_ratio=10``).
    §6 末段: 仅 Span 可定位不构成支持 → span_overlap=False 即 ``insufficient``.

References:
    - docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md §B-1
    - spec §6 末段 — Semantic Support Check
    - spec §11.4 #9 — Evidence Semantic Support Error = 0
    - spec §A2 — Gate SemSupport Accuracy ≥ 0.95
"""
from __future__ import annotations

from .checker import (
    SemanticSupportChecker,
    SupportType,
    SupportVerdict,
)

__all__ = ["SemanticSupportChecker", "SupportVerdict", "SupportType"]
