"""KnowledgeCandidate extension entry point for Mode tag (C-4 / G5).

策略：不修改 KnowledgeCandidate 既有字段语义，仅新增 2 个 back-compat
默认值字段：

* ``knowledge_mode: Literal["observed","synthesized","unknown"] = "unknown"``
* ``failure_reason: str | None = None``

C-0/C-0.5/C-1/C-2/C-3 既有调用方在新增字段上的行为是零变化（字段全部有默认值）。
新的 ``KnowledgeMode`` 行为通过 ``src.kc.contracts.mode`` 模块接入；
``parse_llm_output_with_mode`` 是 fail-closed 入口，5 截断场景在 K-2 加固下
全部返回 ``status=REJECTED`` + ``knowledge_mode="unknown"`` + ``failure_reason``。

spec §7.1 Mode Gate 与既有 4 段 Reviewer 阶段解耦：本模块只负责 mode 标签
与截断兜底，不参与 Confidence/Score/Strength 计算。
"""
from __future__ import annotations

from typing import Literal

# Re-export the public mode contract for downstream imports.
from src.kc.contracts.mode import (  # noqa: F401
    KnowledgeMode,
    detect_truncation,
    parse_knowledge_mode,
    parse_llm_output_with_mode,
)


# 兼容既有 C-0/C-1/C-2/C-3 测试与代码
IntegrityStatus = Literal["verified", "quarantined", "rejected"]


__all__ = [
    "KnowledgeMode",
    "detect_truncation",
    "parse_knowledge_mode",
    "parse_llm_output_with_mode",
    "IntegrityStatus",
]
