"""Tests for IntegrityGate orchestrator (B-3 commit 1).

路线 v2.2 §B-3 — spec §11.2 11 Gate 流水线 orchestrator.

TDD coverage (5 tests):
1. ``IntegrityGate.check(KO_pass_all_gates)`` → passed=True, blocked=False,
   warnings=()
2. ``IntegrityGate.check(KO_blocked_by_evidence_gate)`` → passed=False,
   blocked=True, get_blocking_reasons() 含 'no_evidence'
3. ``IntegrityGate.check(WikiPage_pass_all_gates)`` → passed=True, blocked=False
4. ``IntegrityGate.check(KO_with_legacy_relation)`` → passed=True, blocked=False,
   warnings 含 'legacy_relation_prefer_spec:implements'
5. ``IntegrityGate.check(KO_with_gate_exception)`` → passed=False, blocked=True,
   get_blocking_reasons() 含 'gate_exception:schema:AttributeError'

集成:
- spec §11.2 11 Gate 流水线 (Schema → Provenance → Mode → Evidence → Identity
  → Granularity → Context → Temporal → Conflict → Relation → Retrieval)
- 既有 11 Gate 完整闭环 (B-2.x commits 1-10)
- 任一 Gate block → 标记 blocked (fail-closed)
- Gate 异常 → 视为 block (gate_exception:<name>:<ExceptionType>)

Ref: docs/architecture/B-2_11_Gate_design.md §3-4 + spec §11.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.kc.contracts.evidence import Evidence
from src.kc.integrity.gates import Gate, GateVerdict


# ─── 测试夹具：模拟 KnowledgeObject / WikiPage-like 对象 ────────────────────


@dataclass
class FakeKnowledgeObjectPassAll:
    """KnowledgeObject-like 对象 — 全部 11 Gate 通过.

    字段:
        id, type, title, lifecycle, created_at, updated_at: SchemaGate 必填
        evidence_refs: ProvenanceGate 必填 (C-0.4)
        raw_source_hash: ProvenanceGate 可选 (Z-9 延后)
        confidence, knowledge_mode, claim_type, evidences, derived_from: Evidence Gate
        text: EvidenceGate._is_claim 必填 (text or content + knowledge_mode)
    """
    id: str = "ko_pass_all"
    type: str = "claim"
    title: str = "Test claim"
    lifecycle: str = "active"
    created_at: int = 1700000000000
    updated_at: int = 1700000000000
    evidence_refs: list[str] = field(default_factory=lambda: ["doc_001:b_001"])
    raw_source_hash: str = "abc123"
    confidence: float = 0.95
    knowledge_mode: str = "observed"
    claim_type: str = "fact"
    evidences: list[Evidence] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    ku_id: str = "ku_001"
    text: str = "This is the claim text for evidence gate to detect."


@dataclass
class FakeKnowledgeObjectBlockedByEvidence:
    """KnowledgeObject-like 对象 — EvidenceGate block.

    observed + fact + 无 evidence → insufficient_evidence_strength:observed_fact.
    需要 text 字段以触发 EvidenceGate._is_claim() = True.
    """
    id: str = "ko_blocked_evidence"
    type: str = "claim"
    title: str = "Blocked claim"
    lifecycle: str = "active"
    created_at: int = 1700000000000
    updated_at: int = 1700000000000
    evidence_refs: list[str] = field(default_factory=lambda: ["doc_001:b_001"])
    raw_source_hash: str = "abc123"
    confidence: float = 0.95
    knowledge_mode: str = "observed"
    claim_type: str = "fact"
    evidences: list[Evidence] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    ku_id: str = "ku_002"
    text: str = "This claim has no evidence so EvidenceGate blocks it."


@dataclass
class FakeWikiPagePassAll:
    """WikiPage-like 对象 — 全部 11 Gate 通过.

    字段:
        id, title, type, workflow_state, relations: Retrieval Gate + Relation Gate
    """
    id: str = "wp_pass_all"
    title: str = "Test page"
    type: str = "entity"
    workflow_state: str = "verified"
    relations: list = field(default_factory=list)


@dataclass
class FakeLegacyRelation:
    """Relation-like 对象 (含 type 字段). WikiPage.relations 元素."""
    type: str
    target_id: str = "target_xyz"


@dataclass
class FakeKnowledgeObjectWithLegacyRelation:
    """KO-like 对象 — 含 legacy relation → RelationGate warn (NOT block)."""
    id: str = "ko_legacy_rel"
    type: str = "claim"
    title: str = "Legacy rel claim"
    lifecycle: str = "active"
    created_at: int = 1700000000000
    updated_at: int = 1700000000000
    evidence_refs: list[str] = field(default_factory=lambda: ["doc_001:b_001"])
    raw_source_hash: str = "abc123"
    confidence: float = 0.95
    knowledge_mode: str = "observed"
    claim_type: str = "fact"
    evidences: list[Evidence] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    ku_id: str = "ku_003"
    relations: list = field(
        default_factory=lambda: [FakeLegacyRelation(type="implements")]
    )
    text: str = "Legacy relation claim text."


@dataclass
class FakeKnowledgeObjectBrokenSchema:
    """KO-like 对象 — SchemaGate check 会抛 AttributeError.

    字段: 无 id (None 触发 SchemaGate missing_field:id).

    我们通过覆盖 SchemaGate 实例的 check 来模拟异常更稳定;
    这里直接构造对象, 测试用 monkeypatch 注入 broken schema gate.
    """
    id: str = "ko_broken_schema"
    type: str = "claim"
    title: str = "Broken schema"
    lifecycle: str = "active"
    created_at: int = 1700000000000
    updated_at: int = 1700000000000
    evidence_refs: list[str] = field(default_factory=lambda: ["doc_001:b_001"])
    ku_id: str = "ku_004"


# ─── 强 evidence helper (满足 E-8 observed+fact ≥ 1 strong) ───────────────


def _strong_evidence(ev_id: str = "ev_001") -> Evidence:
    """构造 1 个 strong Evidence (direct_quote, default strong per spec §6 E-2)."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote="matching quote text",
        quote_hash=f"hash_{ev_id}",
        evidence_type="direct_quote",
    )


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestIntegrityGate:
    """spec §11.2 11 Gate 流水线 orchestrator."""

    def test_knowledge_object_passes_all_gates(self):
        """IntegrityGate.check(KO_pass_all_gates) → passed=True, blocked=False, warnings=().

        既有 11 Gate 完整闭环, KO 含强 evidence → 全部通过.
        """
        from src.kc.integrity.orchestrator import IntegrityGate

        ko = FakeKnowledgeObjectPassAll()
        ko.evidences = [_strong_evidence()]  # 1 strong → 满足 E-8

        gate = IntegrityGate()
        report = gate.check(ko)

        assert report.passed is True
        assert report.blocked is False
        assert report.warnings == ()
        # 11 Gate 全部执行
        assert len(report.gate_results) == 11
        # 报告 object_id
        assert report.object_id == "ku_001"

    def test_knowledge_object_blocked_by_evidence_gate(self):
        """IntegrityGate.check(KO_blocked_by_evidence_gate) → blocked=True,
        get_blocking_reasons() 含 'no_evidence' (EvidenceGate 在 evidences 为空
        list 时直接 block, reason='no_evidence', 见 gates.py:272).
        """
        from src.kc.integrity.orchestrator import IntegrityGate

        ko = FakeKnowledgeObjectBlockedByEvidence()
        ko.evidences = []  # 无 evidence → EvidenceGate no_evidence block

        gate = IntegrityGate()
        report = gate.check(ko)

        assert report.passed is False
        assert report.blocked is True
        blocking_reasons = report.get_blocking_reasons()
        assert "no_evidence" in blocking_reasons

    def test_wiki_page_passes_all_gates(self):
        """IntegrityGate.check(WikiPage_pass_all_gates) → passed=True, blocked=False.

        WikiPage 无 evidence_refs / ku_id / knowledge_mode 等 KO 字段,
        各 Gate 通过 hasattr 探测视为不适用 → 全部 pass.
        """
        from src.kc.integrity.orchestrator import IntegrityGate

        page = FakeWikiPagePassAll()

        gate = IntegrityGate()
        report = gate.check(page)

        assert report.passed is True
        assert report.blocked is False
        assert len(report.gate_results) == 11

    def test_knowledge_object_with_legacy_relation_warns(self):
        """IntegrityGate.check(KO_with_legacy_relation) → passed=True, blocked=False,
        warnings 含 'legacy_relation_prefer_spec:implements'.
        """
        from src.kc.integrity.orchestrator import IntegrityGate

        ko = FakeKnowledgeObjectWithLegacyRelation()
        ko.evidences = [_strong_evidence()]  # 1 strong → EvidenceGate pass

        gate = IntegrityGate()
        report = gate.check(ko)

        # legacy relation → warn (不阻断)
        assert report.passed is True
        assert report.blocked is False
        assert "legacy_relation_prefer_spec:implements" in report.warnings

    def test_knowledge_object_gate_exception_blocks(self, monkeypatch):
        """IntegrityGate.check(KO_with_gate_exception) → blocked=True,
        get_blocking_reasons() 含 'gate_exception:schema:AttributeError'.
        """
        from src.kc.integrity import orchestrator as orch_module

        ko = FakeKnowledgeObjectBrokenSchema()

        # 替换 IntegrityGate._gates 的第一个 (schema gate), 强制抛 AttributeError
        original_gates = orch_module.IntegrityGate.__init__

        class BrokenSchemaGate(Gate):
            name = "schema"
            order = 1

            def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
                raise AttributeError("simulated schema gate crash")

        # 替换 module-level IntegrityGate._gates: monkeypatch 第一位为 BrokenSchemaGate
        gate_instance = orch_module.IntegrityGate()

        # 保存原 gates, 替换 schema gate
        original_gates_list = list(gate_instance._gates)
        new_gates = (BrokenSchemaGate(),) + tuple(original_gates_list[1:])
        gate_instance._gates = new_gates

        report = gate_instance.check(ko)

        # fail-closed: 异常视为 block
        assert report.passed is False
        assert report.blocked is True
        blocking_reasons = report.get_blocking_reasons()
        assert any(
            "gate_exception:schema:AttributeError" in r for r in blocking_reasons
        )
