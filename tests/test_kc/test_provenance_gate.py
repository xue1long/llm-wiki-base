"""Tests for Provenance Gate (B-2.1 commit 2).

路线 v2.2 §B-2.1 commit 2 — 试水阶段：Provenance Gate (spec §11.2 Gate 2)
+ spec §5.7 Evidence + §3.3 Raw Source 只读 + §6 Evidence Strength。

TDD coverage (3 tests):
1. ProvenanceGate.check(KnowledgeObject(evidence_refs=[])) 返回 block + no_evidence_refs
2. ProvenanceGate.check(KnowledgeObject(evidence_refs=["ev_001"])) 返回 pass
3. ProvenanceGate.check(Evidence-like 携带 quote + block_content 且 quote 在内) → pass；
   不在内 → block (quote_not_in_block)

Ref: docs/architecture/B-2_11_Gate_design.md §3.2 + spec §11.2/§5.7/§3.3/§6
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.contracts.evidence import Evidence
from src.kc.integrity.gates import GateVerdict, ProvenanceGate
from src.knowledge.core.object import KnowledgeObject, KnowledgeType, LifecycleState, Provenance


# ─── 测试夹具：携带 quote + block_content 的轻量类 ──────────────────────────────
# ProvenanceGate 通过 hasattr 检查 quote + block_content 是否同时存在
# (spec §6 末段 + C-1 validate_evidence); 真实 Evidence 没有 block_content
# 字段, 因为 block_content 在 Evidence 校验时由 caller 提供。
# 这里用一个 dataclass 完整模拟 quote_in_block 维度。


@dataclass
class EvidenceLikeQuoteInBlock:
    """模拟 Evidence + block_content 一起存在的对象（用于 quote_in_block 维度校验）。"""

    evidence_id: str
    document_id: str
    block_id: str
    quote: str
    quote_hash: str
    block_content: str  # ProvenanceGate 通过 hasattr 检查此字段


# ─── Test 1: KnowledgeObject.evidence_refs 为空 → block ────────────────────


def test_provenance_gate_knowledge_object_with_empty_evidence_refs_blocks():
    """KnowledgeObject.evidence_refs=[] → ProvenanceGate block + no_evidence_refs。"""
    obj = KnowledgeObject(
        id="ko_001",
        type=KnowledgeType.ENTITY,
        title="Some Entity",
        content="entity body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="raw/foo.md"),
    )
    # KnowledgeObject dataclass 默认没有 evidence_refs 字段;
    # ProvenanceGate 通过 hasattr 探测, 这里显式设置空列表模拟缺失
    obj.evidence_refs = []  # C-0.4 字段语义; 空 → no_evidence_refs

    gate = ProvenanceGate()
    verdict = gate.check(obj)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert "no_evidence_refs" in verdict.reasons


# ─── Test 2: KnowledgeObject.evidence_refs 非空 → pass ─────────────────────


def test_provenance_gate_knowledge_object_with_evidence_refs_passes():
    """KnowledgeObject.evidence_refs=["ev_001"] → ProvenanceGate pass。

    KnowledgeObject dataclass 不是 frozen, 可以直接 setattr evidence_refs。
    """
    obj = KnowledgeObject(
        id="ko_002",
        type=KnowledgeType.ENTITY,
        title="Some Entity",
        content="entity body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="raw/foo.md"),
    )
    obj.evidence_refs = ["ev_001"]  # C-0.4 字段; 非空即通过

    gate = ProvenanceGate()
    verdict = gate.check(obj)
    assert verdict.passed is True
    assert verdict.severity == "info"
    assert verdict.blocked is False


# ─── Test 3: Evidence quote_in_block 维度 ───────────────────────────────────


def test_provenance_gate_evidence_quote_in_block_passes_or_blocks():
    """quote 在 block_content 内 → pass；不在 → block + quote_not_in_block。"""
    gate = ProvenanceGate()

    # (a) quote 在 block_content 内 → pass
    in_block = EvidenceLikeQuoteInBlock(
        evidence_id="ev_001",
        document_id="doc_001",
        block_id="b_001",
        quote="hello world",
        quote_hash="hash_001",
        block_content="This block says hello world clearly.",
    )
    verdict_pass = gate.check(in_block)
    assert verdict_pass.passed is True
    assert verdict_pass.severity == "info"
    assert verdict_pass.blocked is False

    # (b) quote 不在 block_content 内 → block
    not_in_block = EvidenceLikeQuoteInBlock(
        evidence_id="ev_002",
        document_id="doc_001",
        block_id="b_002",
        quote="completely different text",
        quote_hash="hash_002",
        block_content="This block has nothing to do with the quote.",
    )
    verdict_block = gate.check(not_in_block)
    assert verdict_block.passed is False
    assert verdict_block.severity == "block"
    assert verdict_block.blocked is True
    assert "quote_not_in_block" in verdict_block.reasons


# ─── 辅助 imports 验证（保证模块结构正确） ─────────────────────────────────


def test_provenance_gate_class_attributes():
    """ProvenanceGate 暴露 name='provenance' + order=2（spec §11.2 顺序）。"""
    g = ProvenanceGate()
    assert g.name == "provenance"
    assert g.order == 2