"""Tests for Mode Gate (B-2.3 — spec §11.2 Gate 4 + §7 Observed/Synthesized rules).

路线 v2.2 §B-2.3 — Mode Gate 试水 + 完整实现.

TDD coverage (5 tests):
1. ModeGate.check(claim_with_observed_mode) → pass
   (C-4 KnowledgeMode 字段已固化, observed 合法)
2. ModeGate.check(claim_with_synthesized_mode_and_derived_from_and_approved) → pass
   (spec §7.3 synthesized 完整来源链 + review_status=approved)
3. ModeGate.check(claim_with_synthesized_mode_but_no_derived_from) → block +
   missing_derived_from:synthesized (spec §7.3 缺推导链)
4. ModeGate.check(claim_with_knowledge_mode_none) → block +
   knowledge_mode_is_none (spec §7.3 Agent Context 不得省略知识模式)
5. ModeGate.check(non_knowledge_object) → pass
   (helper: 无 knowledge_mode 字段的对象不在本 Gate 关注范围)

Ref: docs/architecture/B-2_11_Gate_design.md §3.4 + spec §11.2/§7 + C-4 mode.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


from src.kc.integrity.gates import ModeGate


# ─── 测试夹具：Claim-like 对象 ──────────────────────────────────────────────
# Mode Gate 通过 hasattr 探测 knowledge_mode + derived_from + 合成字段。
# 这里用一个 dataclass 模拟 claim 形态（spec §7 Gate 入参）。


@dataclass
class ClaimLike:
    """模拟 Claim 对象（Mode Gate 入参).

    Attributes:
        id:                     Claim 唯一标识
        text:                   Claim 文本
        knowledge_mode:         "observed" | "synthesized" | "unknown"
        derived_from:           synthesized 必填的推导来源 IDs (spec §7.3)
        synthesis_provenance:   synthesized 必填的合成 Provenance (spec §7.3)
        review_status:          "approved" | "pending" | "rejected" (spec §7.3)
        version:                synthesized 重新生成的版本号 (spec §7.3)
    """

    id: str = "claim_001"
    text: str = "Some claim"
    knowledge_mode: str = "observed"
    derived_from: list[str] = field(default_factory=list)
    synthesis_provenance: dict | None = None
    review_status: str = "approved"
    version: int = 1


# ─── 辅助：非 Knowledge 对象（无 knowledge_mode 字段）─────────────────────────


@dataclass
class NonKnowledgeObject:
    """Mode Gate 不关注的非 knowledge 对象 (helper)."""

    id: str = "x"
    value: int = 42


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestModeGate:
    """spec §11.2 Gate 4 + §7 全部规则."""

    def test_observed_mode_passes(self):
        """Observed Mode + 合法字段 → pass (spec §7.1)."""
        gate = ModeGate()
        claim = ClaimLike(knowledge_mode="observed")

        verdict = gate.check(claim)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_synthesized_with_full_provenance_passes(self):
        """Synthesized + derived_from + synthesis_provenance + approved → pass (spec §7.3)."""
        gate = ModeGate()
        claim = ClaimLike(
            knowledge_mode="synthesized",
            derived_from=["src_001", "src_002"],
            synthesis_provenance={
                "method": "abductive",
                "sources": ["src_001", "src_002"],
            },
            review_status="approved",
            version=2,
        )

        verdict = gate.check(claim)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_synthesized_without_derived_from_blocks(self):
        """Synthesized + 无 derived_from → block + missing_derived_from:synthesized (spec §7.3)."""
        gate = ModeGate()
        claim = ClaimLike(
            knowledge_mode="synthesized",
            derived_from=[],  # 空 → 缺推导链
            synthesis_provenance={"method": "abductive"},
            review_status="approved",
        )

        verdict = gate.check(claim)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "missing_derived_from:synthesized" in verdict.reasons

    def test_knowledge_mode_none_blocks(self):
        """knowledge_mode=None → block + knowledge_mode_is_none (spec §7.3 Agent Context 不得省略)."""
        gate = ModeGate()
        claim = ClaimLike(knowledge_mode="observed")
        # 强制设 None 模拟截断兜底后的状态（C-4 K-2 加固场景 4: value_null_or_empty）
        claim.knowledge_mode = None

        verdict = gate.check(claim)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "knowledge_mode_is_none" in verdict.reasons

    def test_non_knowledge_object_passes(self):
        """非 knowledge 对象（无 knowledge_mode 字段）→ pass（不在本 Gate 关注范围）."""
        gate = ModeGate()
        obj = NonKnowledgeObject(id="x", value=42)

        verdict = gate.check(obj)

        # 无 knowledge_mode 字段视为 pass（helper：不适用, 不强制校验）
        assert verdict.passed is True
        assert verdict.blocked is False
