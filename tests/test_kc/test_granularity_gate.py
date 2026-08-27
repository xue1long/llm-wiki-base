"""Tests for Granularity Gate (B-2.5 commit 2 — spec §11.2 Gate 6 + §4.2 + §4.4).

路线 v2.2 §B-2.5 — Granularity Gate 完整实现 + 关闭 B-2.4 Identity Gate known_limitations.

TDD coverage (5 tests):
1. ``GranularityGate.check(non_knowledge_unit_object)`` → pass (helper: 非 KU 不适用)
2. ``GranularityGate.check(KU_with_missing_question)`` → block +
   ``missing_question:ku_cannot_be_described`` (spec §4.2)
3. ``GranularityGate.check(KU_with_valid_question)`` → pass
4. ``GranularityGate.check(KU_with_should_split_params_no_resolution_event)`` → block +
   ``split_triggered_no_resolution_event`` (spec §4.4 + A-1 should_split_ku 集成)
5. ``GranularityGate.check(KU_with_deprecated_status_no_resolution_event)`` → warn +
   ``deprecated_without_resolution_event`` (spec §4.4 + A-1 commit 2 ResolutionEvent 集成)

集成:
- A-1 commit 1 KnowledgeUnit.question (spec §4.2 必填)
- A-1 commit 1 should_split_ku (spec §4.4 拆分 4 条件 OR-of)
- A-1 commit 1 should_merge_ku (spec §4.4 合并 5 条件 AND-of)
- A-1 commit 2 scripts/kc_record_resolution_event.py 提供
  make_event_from_split_decision() + make_event_from_merge_decision() —
  KU 通过 resolution_event_id 字段关联 (B-2.5 commit 1 字段已加)
- B-2.4 Identity Gate 留下的 known_limitations 第 5 项
  "拆分/合并决策应写入 ResolutionEvent" 现已关闭

Ref: docs/architecture/B-2_11_Gate_design.md §3.6 + spec §11.2/§4.2/§4.4/§5.11
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.domain import KnowledgeUnit
from src.kc.integrity.gates import GateVerdict, GranularityGate


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


def _make_ku(**overrides) -> KnowledgeUnit:
    """Helper: 构造真实 KU with overrides."""
    defaults = {
        "ku_id": "ku_test_001",
        "concept_id": "concept_001",
        "question": "What is X?",
        "title": "X",
        "unit_type": "definition",
        "knowledge_mode": "observed",
        "status": "candidate",
    }
    defaults.update(overrides)
    return KnowledgeUnit(**defaults)


# ─── 辅助：非 KnowledgeUnit 对象 ─────────────────────────────────────────────


@dataclass
class NonKnowledgeUnitObject:
    """Granularity Gate 不关注的非 KU 对象 (helper)."""

    id: str = "x"
    value: int = 42


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestGranularityGate:
    """spec §11.2 Gate 6: 对象粒度符合三层模型."""

    def test_non_knowledge_unit_object_passes(self):
        """非 KU 对象 → pass (helper: 不在本 Gate 关注范围)."""
        gate = GranularityGate()
        obj = NonKnowledgeUnitObject(id="x", value=42)

        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ku_with_missing_question_blocks(self):
        """KU 无 question 字段 → block + missing_question:ku_cannot_be_described
        (spec §4.2: KU 必须能用一个问题描述)."""
        gate = GranularityGate()
        # 显式构造 question="" (空字符串) → 触发 missing_question
        ku = _make_ku(question="")

        verdict = gate.check(ku)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "missing_question:ku_cannot_be_described" in verdict.reasons

    def test_ku_with_valid_question_passes(self):
        """KU + 合法 question → pass (spec §4.2)."""
        gate = GranularityGate()
        ku = _make_ku(question="What is retrieval-augmented generation?")

        verdict = gate.check(ku)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ku_with_should_split_params_no_resolution_event_blocks(self):
        """KU + should_split_ku()=True 但无 resolution_event_id → block +
        split_triggered_no_resolution_event (spec §4.4 + A-1 commit 2)."""
        gate = GranularityGate()
        ku = _make_ku(question="Q?", resolution_event_id=None)

        # 通过 context 传入拆分判定参数: internal_questions=2 → should_split_ku returns True
        context = {"should_split_params": {"claim_count": 2, "internal_questions": 2}}

        verdict = gate.check(ku, context=context)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "split_triggered_no_resolution_event" in verdict.reasons

    def test_ku_with_deprecated_status_no_resolution_event_warns(self):
        """KU status='deprecated' 但无 resolution_event_id → warn +
        deprecated_without_resolution_event (spec §4.4 软告警)."""
        gate = GranularityGate()
        ku = _make_ku(status="deprecated", resolution_event_id=None)

        verdict = gate.check(ku)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "deprecated_without_resolution_event" in verdict.reasons