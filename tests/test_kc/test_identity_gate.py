"""Tests for Identity Gate (B-2.4 — spec §11.2 Gate 5 + §5.4 KU + §5.11 Approval + §11.4 #4).

路线 v2.2 §B-2.4 — Identity Gate 试水 + 简化实现.

TDD coverage (5 tests):
1. ``IdentityGate.check(non_knowledge_unit_object)`` → pass
   (helper: 非 KU 对象不在本 Gate 关注范围)
2. ``IdentityGate.check(KU_with_valid_identity_key)`` → pass
   (A-1 id-v1 算法自动计算 identity_key → 合法)
3. ``IdentityGate.check(KU_with_invalid_identity_key_format)`` → block +
   ``invalid_identity_key_format`` (如 identity_key 不以 ``id-v1:`` 开头)
4. ``IdentityGate.check(KU_with_approval_gate_and_missing_approval)`` → warn +
   ``missing_approval:high_risk_operation`` (spec §11.4 #4 "无审计 merge/supersede = 0")
5. helper: ``IdentityGate.name == "identity"`` + ``order == 5``

Ref: docs/architecture/B-2_11_Gate_design.md §3.5 + spec §11.2/§5.4/§5.11/§11.4 #4
+ spec §4.4 KU 合并条件 + A-1 KnowledgeUnit + A-4 ApprovalGate.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.integrity.gates import IdentityGate


# ─── 测试夹具：KnowledgeUnit 对象 ─────────────────────────────────────────────
# Identity Gate 通过 isinstance 检查 KU；用真实 KnowledgeUnit dataclass 测试
# identity_key @property 自动计算（A-1 已固化 id-v1 算法）。


def _make_ku(
    ku_id: str = "ku_test_001",
    concept_id: str = "concept_001",
    question: str = "What is X?",
    title: str = "X",
    unit_type: str = "definition",
    knowledge_mode: str = "observed",
    status: str = "candidate",
) -> KnowledgeUnit:
    """Helper: 构造真实 KU（identity_key 由 @property 自动计算 id-v1:xxx）."""
    return KnowledgeUnit(
        ku_id=ku_id,
        concept_id=concept_id,
        question=question,
        title=title,
        unit_type=unit_type,
        knowledge_mode=knowledge_mode,
        status=status,
    )


# ─── 辅助：非 KnowledgeUnit 对象 ─────────────────────────────────────────────


@dataclass
class NonKnowledgeUnitObject:
    """Identity Gate 不关注的非 KU 对象 (helper)."""

    id: str = "x"
    value: int = 42


# ─── TDD 测试 ────────────────────────────────────────────────────────────────


class TestIdentityGate:
    """spec §11.2 Gate 5: 概念归属和别名解析可解释."""

    def test_non_knowledge_unit_object_passes(self):
        """非 KU 对象 → pass (helper: 不在本 Gate 关注范围)."""
        gate = IdentityGate()
        obj = NonKnowledgeUnitObject(id="x", value=42)

        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ku_with_valid_identity_key_passes(self):
        """KU + 合法 identity_key (@property 自动 id-v1) → pass (spec §5.4)."""
        gate = IdentityGate()
        ku = _make_ku()  # id-v1:sha256hex 由 @property 自动生成

        verdict = gate.check(ku)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False
        # Sanity: identity_key 必须以 id-v1: 开头
        assert ku.identity_key.startswith("id-v1:")

    def test_ku_with_invalid_identity_key_format_blocks(self):
        """KU + identity_key 不以 ``id-v1:`` 开头 → block + invalid_identity_key_format."""
        gate = IdentityGate()
        ku = _make_ku()

        # 用 PropertyMock 替换 @property 让其返回非法值
        # (模拟"手工篡改"或"缺失计算"场景 — KnowledgeUnit 是 frozen dataclass,
        # 真实数据库层绕过 @property 直接写入字段的情况)
        with patch.object(
            KnowledgeUnit,
            "identity_key",
            new_callable=lambda: property(lambda self: "invalid:xxx"),
        ):
            verdict = gate.check(ku)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "invalid_identity_key_format" in verdict.reasons

    def test_ku_with_approval_gate_missing_approval_warns(self):
        """KU (verified) + ApprovalGate 无 approved approval → warn +
        missing_approval:high_risk_operation (spec §11.4 #4)."""
        from src.kc.governance.approval import ApprovalGate

        gate = IdentityGate(approval_gate=ApprovalGate())
        # status='verified' 隐含已通过合并路径 → 需要 approved approval
        ku = _make_ku(status="verified")

        verdict = gate.check(ku)

        # 高风险操作缺 approval → warn (软告警, 非 block — 因 caller 可能正在请求)
        assert verdict.passed is True
        assert verdict.severity == "warn"
        assert "missing_approval:high_risk_operation" in verdict.reasons

    def test_gate_metadata(self):
        """helper: IdentityGate.name == "identity" + order == 5 (spec §11.2 顺序)."""
        gate = IdentityGate()

        assert gate.name == "identity"
        assert gate.order == 5
