"""Tests for Evidence Gate (B-2.2 — spec §11.2 Gate 3 + §6 全部 15 条规则 + B-1 集成).

路线 v2.2 §B-2.2 — Evidence Gate 试水 + 完整实现.

TDD coverage (6 tests):
1. EvidenceGate.check(claim_with_1_strong_evidence) → pass
   (observed+fact 满足 E-8: 至少 1 strong)
2. EvidenceGate.check(claim_with_2_medium_evidences) → pass
   (E-8: 至少 2 独立 medium)
3. EvidenceGate.check(claim_with_0_evidence) → block + no_evidence
4. EvidenceGate.check(claim_with_only_weak_evidence) → block +
   insufficient_evidence_strength:observed_fact (E-8 不满足)
5. EvidenceGate.check(synthesized_claim_without_derived_from) → block +
   missing_derived_from:synthesized (E-10 不满足)
6. EvidenceGate.check(claim_with_rejected_source_trust) → block +
   rejected_source_trust (E-12 阻断)

Ref: docs/architecture/B-2_11_Gate_design.md §3.3 + spec §11.2/§6 + B-1.
"""
from __future__ import annotations

from dataclasses import dataclass, field


from src.kc.contracts.evidence import Evidence
from src.kc.integrity.gates import EvidenceGate
from src.kc.semantic_support.checker import SemanticSupportChecker


# ─── 测试夹具：Claim-like 对象 ──────────────────────────────────────────────
# Claim 目前没有正式 dataclass（spec §5.4 定义在 KU 层级），
# EvidenceGate 通过 hasattr 探测特征 (text/content + knowledge_mode + evidences)。
# 这里用一个 dataclass 模拟 claim 形态（spec §6 末段 Evidence Gate 入参）。


@dataclass
class ClaimLike:
    """模拟 Claim 对象（EvidenceGate 入参).

    Attributes:
        id:            Claim 唯一标识
        text:          Claim 文本（用于 SemanticSupportChecker 对齐）
        knowledge_mode: "observed" | "synthesized" | "unknown"
        claim_type:    "fact" | "opinion" | "perspective"
        evidences:     关联 Evidence 列表
        derived_from:  synthesized 必填（spec §6 E-10）
        trust_profile_status:  "accepted" | "restricted" | "rejected" | None
    """

    id: str
    text: str
    knowledge_mode: str = "observed"
    claim_type: str = "fact"
    evidences: list[Evidence] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    trust_profile_status: str | None = None


# ─── 测试辅助：构造 Evidence with explicit type + provenance ──────────────


def _direct_quote(ev_id: str, quote: str = "matching quote text") -> Evidence:
    """direct_quote Evidence (default strong per spec §6 E-2)."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote=quote,
        quote_hash=f"hash_{ev_id}",
        evidence_type="direct_quote",
    )


def _structured_source_strong(ev_id: str, quote: str = "structured field") -> Evidence:
    """structured_source with full provenance → strong (E-3 + E-15 satisfied)."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote=quote,
        quote_hash=f"hash_{ev_id}",
        evidence_type="structured_source",
        structured_provenance={
            "schema_id": "schema_v1",
            "record_key": "row_001",
            "field_path": "col.value",
        },
    )


def _structured_source_weak(ev_id: str, quote: str = "structured field") -> Evidence:
    """structured_source missing required fields → weak per E-15."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote=quote,
        quote_hash=f"hash_{ev_id}",
        evidence_type="structured_source",
        structured_provenance={"schema_id": "schema_v1"},  # missing record_key + field_path
    )


def _computed_weak(ev_id: str, quote: str = "computed value") -> Evidence:
    """computed missing required fields → weak per E-14."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote=quote,
        quote_hash=f"hash_{ev_id}",
        evidence_type="computed",
        computation_provenance={"algorithm": "mean"},  # missing 3 others
    )


def _multi_source_medium(ev_id: str, quote: str = "matching multi source") -> Evidence:
    """multi_source Evidence (default medium per spec §6 E-6)."""
    return Evidence(
        evidence_id=ev_id,
        document_id="doc_001",
        block_id="b_001",
        quote=quote,
        quote_hash=f"hash_{ev_id}",
        evidence_type="multi_source",
    )


# ─── Test 1: observed+fact + 1 strong evidence → pass (E-8) ────────────────


def test_evidence_gate_claim_with_one_strong_evidence_passes():
    """observed+fact 配 1 strong Evidence (direct_quote) → pass (E-8 满足)."""
    claim = ClaimLike(
        id="claim_001",
        text="这是一段匹配的引用文本",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[_direct_quote("ev_strong_001", quote="这是一段匹配的引用文本")],
    )
    gate = EvidenceGate()
    verdict = gate.check(claim)
    assert verdict.passed is True
    assert verdict.severity in ("info", "warn")
    assert verdict.blocked is False


# ─── Test 2: observed+fact + 2 medium evidences → pass (E-8 alt) ───────────


def test_evidence_gate_claim_with_two_medium_evidences_passes():
    """observed+fact 配 2 medium Evidence (multi_source) → pass (E-8 alt: ≥2 medium)."""
    claim = ClaimLike(
        id="claim_002",
        text="多源支持文本",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[
            _multi_source_medium("ev_med_001", quote="多源支持文本 a"),
            _multi_source_medium("ev_med_002", quote="多源支持文本 b"),
        ],
    )
    gate = EvidenceGate()
    verdict = gate.check(claim)
    assert verdict.passed is True
    assert verdict.blocked is False


# ─── Test 3: claim with no evidence → block (no_evidence) ─────────────────


def test_evidence_gate_claim_with_no_evidence_blocks():
    """observed+fact 0 evidence → block + reasons 含 no_evidence."""
    claim = ClaimLike(
        id="claim_003",
        text="some claim",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[],
    )
    gate = EvidenceGate()
    verdict = gate.check(claim)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert "no_evidence" in verdict.reasons


# ─── Test 4: claim with only weak evidence → block (E-8 fail) ─────────────


def test_evidence_gate_claim_with_only_weak_evidence_blocks():
    """observed+fact 仅 weak Evidence → block + insufficient_evidence_strength:observed_fact.

    用 1 条 structured_source_weak (E-15 降级到 weak).
    """
    claim = ClaimLike(
        id="claim_004",
        text="weak only",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[_structured_source_weak("ev_weak_001")],
    )
    gate = EvidenceGate()
    verdict = gate.check(claim)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert any(
        r.startswith("insufficient_evidence_strength:observed_fact")
        for r in verdict.reasons
    ), f"expected insufficient_evidence_strength:observed_fact in {verdict.reasons!r}"


# ─── Test 5: synthesized claim without derived_from → block (E-10) ────────


def test_evidence_gate_synthesized_without_derived_from_blocks():
    """synthesized 缺 derived_from → block + missing_derived_from:synthesized (E-10)."""
    claim = ClaimLike(
        id="claim_005",
        text="synthesized claim",
        knowledge_mode="synthesized",
        claim_type="fact",
        evidences=[_direct_quote("ev_strong_005", quote="synthesized claim")],
        derived_from=[],  # E-10 不满足
    )
    gate = EvidenceGate()
    verdict = gate.check(claim)
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert any(
        r.startswith("missing_derived_from:synthesized") for r in verdict.reasons
    ), f"expected missing_derived_from:synthesized in {verdict.reasons!r}"


# ─── Test 6: claim with rejected source trust → block (E-12) ───────────────


def test_evidence_gate_rejected_source_trust_blocks():
    """trust_profile_status='rejected' → block + rejected_source_trust (E-12)."""
    claim = ClaimLike(
        id="claim_006",
        text="rejected source claim",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[_direct_quote("ev_strong_006", quote="rejected source claim")],
        trust_profile_status="rejected",
    )
    gate = EvidenceGate()
    verdict = gate.check(claim, context={"trust_profile_id": "tp_006"})
    assert verdict.passed is False
    assert verdict.severity == "block"
    assert verdict.blocked is True
    assert "rejected_source_trust" in verdict.reasons


def test_evidence_gate_rule_based_semantic_failure_blocks() -> None:
    """Rule-based semantic failure blocks without needing runtime judgment."""
    claim = ClaimLike(
        id="claim_007",
        text="Mitochondria are the powerhouse of the cell",
        knowledge_mode="observed",
        claim_type="fact",
        evidences=[_direct_quote("ev_strong_007", quote="量子纠缠是物理学现象")],
    )
    gate = EvidenceGate(semantic_checker=SemanticSupportChecker())

    verdict = gate.check(claim, context={"evidences": claim.evidences})

    assert verdict.passed is False
    assert verdict.blocked is True
    assert "insufficient_semantic_support:ev_strong_007" in verdict.reasons


# ─── 辅助 imports 验证（保证模块结构正确）────────────────────────────────


def test_evidence_gate_class_attributes():
    """EvidenceGate 暴露 name='evidence' + order=3 (spec §11.2 顺序)."""
    g = EvidenceGate()
    assert g.name == "evidence"
    assert g.order == 3


def test_evidence_gate_non_claim_object_passes():
    """EvidenceGate 对非 Claim 对象 (无 knowledge_mode) 直接 pass (不适用).

    SchemaGate 已经管对象类型识别, EvidenceGate 只针对 Claim 特征对象工作。
    """
    gate = EvidenceGate()

    # 普通无 claim 特征的对象 → pass
    class _PlainObject:
        pass

    verdict = gate.check(_PlainObject())
    assert verdict.passed is True
    assert verdict.blocked is False
