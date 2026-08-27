"""Tests for 11 Gate 基类 + GateVerdict + Schema Gate (B-2.1 commit 1).

路线 v2.2 §B-2.1 — 试水阶段：Schema Gate (spec §11.2 Gate 1)
+ 公共契约 GateVerdict + Gate 基类。

TDD coverage (5 tests):
1. GateVerdict.pass_() 返回 passed=True severity=info
2. GateVerdict.block(["reason1"]) 返回 passed=False severity=block blocked=True
3. SchemaGate.check(KnowledgeObject(全部必填字段)) 返回 pass
4. SchemaGate.check(KnowledgeObject(缺 title)) 返回 block + reasons 含 missing_field:title
5. SchemaGate.check(Evidence(quote_hash 为空字符串)) 返回 block + missing_field:quote_hash

Ref: docs/architecture/B-2_11_Gate_design.md §3.1 + spec §11.2
"""
from __future__ import annotations

import pytest

from src.kc.contracts.evidence import Evidence
from src.kc.governance.approval import Approval
from src.kc.integrity.gates import Gate, GateVerdict, SchemaGate
from src.kc.domain.knowledge_unit import KnowledgeUnit, ResolutionEvent
from src.kc.contracts.structured_fact import StructuredFact
from src.kc.conflicts.classifier import Conflict
from src.knowledge.core.object import KnowledgeObject, KnowledgeType, LifecycleState, Provenance


# ─── Test 1: GateVerdict.pass_() ────────────────────────────────────────────


def test_gate_verdict_pass_returns_info_severity():
    """GateVerdict.pass_() 返回 passed=True severity=info blocked=False。"""
    v = GateVerdict.pass_()
    assert v.passed is True
    assert v.severity == "info"
    assert v.blocked is False
    assert "pass" in v.reasons


# ─── Test 2: GateVerdict.block(["reason1"]) ─────────────────────────────────


def test_block_verdict_returns_block_severity_and_reasons():
    """GateVerdict.block(["reason1"]) 返回 passed=False severity=block blocked=True。"""
    v = GateVerdict.block(["reason1", "reason2"])
    assert v.passed is False
    assert v.severity == "block"
    assert v.blocked is True
    assert "reason1" in v.reasons
    assert "reason2" in v.reasons


# ─── Test 3: SchemaGate 对完整 KnowledgeObject pass ─────────────────────────


def test_schema_gate_knowledge_object_with_all_required_fields_passes():
    """KnowledgeObject 全部必填字段存在 → SchemaGate pass。"""
    obj = KnowledgeObject(
        id="ko_001",
        type=KnowledgeType.ENTITY,
        title="Some Entity",
        content="entity body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="raw/foo.md"),
    )
    gate = SchemaGate()
    verdict = gate.check(obj)
    assert verdict.passed is True
    assert verdict.severity == "info"
    assert verdict.blocked is False


# ─── Test 4: SchemaGate 缺 title 必填 → block ──────────────────────────────


def test_schema_gate_missing_required_field_blocks_with_reason_code():
    """KnowledgeObject 缺 title → SchemaGate block, reasons 含 missing_field:title。"""
    # Bypass dataclass defaults by passing all fields except title empty via setattr.
    # KnowledgeObject has content/type/etc as positional; build with title="" to simulate.
    obj = KnowledgeObject(
        id="ko_002",
        type=KnowledgeType.ENTITY,
        title="",  # 空字符串 — required but missing
        content="entity body",
        lifecycle=LifecycleState.ACTIVE,
        confidence=0.9,
        provenance=Provenance(source_path="raw/foo.md"),
    )
    gate = SchemaGate()
    verdict = gate.check(obj)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert any("missing_field:title" in r for r in verdict.reasons), (
        f"expected missing_field:title in reasons, got {verdict.reasons!r}"
    )


# ─── Test 5: SchemaGate Evidence quote_hash 为空 → block ─────────────────────


def test_schema_gate_evidence_missing_quote_hash_blocks():
    """Evidence(quote_hash="") → SchemaGate block, reasons 含 missing_field:quote_hash。"""
    # Evidence is frozen; build with quote_hash="" (empty string == absent).
    ev = Evidence(
        evidence_id="ev_001",
        document_id="doc_001",
        block_id="b_001",
        quote="some quote",
        quote_hash="",  # 空字符串 — required but missing
    )
    gate = SchemaGate()
    verdict = gate.check(ev)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert any("missing_field:quote_hash" in r for r in verdict.reasons), (
        f"expected missing_field:quote_hash in reasons, got {verdict.reasons!r}"
    )


# ─── 辅助 imports 验证（保证模块结构正确） ─────────────────────────────────


def test_schema_gate_class_attributes():
    """SchemaGate 暴露 name='schema' + order=1（spec §11.2 顺序）。"""
    g = SchemaGate()
    assert g.name == "schema"
    assert g.order == 1