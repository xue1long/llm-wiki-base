"""Knowledge Core domain models (A-1 / G3, spec §4.2 + §5.4).

Exposes:
- KnowledgeUnit: 三层粒度中层 (spec §4.2)
- compute_ku_identity_key: id-v1 identity derivation
- should_split_ku / should_merge_ku: spec §4.4 决策辅助
- ResolutionEvent: spec §5.11 拆分/合并决策日志
"""
from .knowledge_unit import (
    KnowledgeUnit,
    UnitType,
    KUStatus,
    ResolutionAction,
    compute_ku_identity_key,
    should_split_ku,
    should_merge_ku,
    ResolutionEvent,
)
from .ids import block_id, document_id

__all__ = [
    "KnowledgeUnit",
    "UnitType",
    "KUStatus",
    "ResolutionAction",
    "compute_ku_identity_key",
    "should_split_ku",
    "should_merge_ku",
    "ResolutionEvent",
    "block_id",
    "document_id",
]
