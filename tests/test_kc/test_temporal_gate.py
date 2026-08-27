"""Tests for Temporal Gate (B-2.7 — spec §11.2 Gate 8 + §10 Temporal Validity).

路线 v2.2 §B-2.7 — Temporal Gate 完整实现.

TDD coverage (5 tests):
1. ``TemporalGate.check(obj_without_valid_from_valid_to)`` → pass (helper: WikiPage
   等无 valid_from/valid_to 字段的对象不适用 — A-2 仅在 KnowledgeObject 加字段)
2. ``TemporalGate.check(KO_with_both_bounds_none)`` → warn +
   ``unknown_temporal:both_bounds_none`` (spec §10 T-2 / T-9 — 缺任一边界 → unknown;
   默认当前检索不返回)
3. ``TemporalGate.check(KO_with_invalid_temporal_valid_from_gt_valid_to)`` → block +
   ``invalid_temporal:valid_from_gt_valid_to`` (spec §10 — valid_from > valid_to
   即非法时间区间, 阻断)
4. ``TemporalGate.check(KO_with_valid_from_in_future_query_time_in_past)`` → warn +
   ``temporal_status:scheduled`` (spec §10 T-9 — 未来生效 → scheduled, warn 默认
   不阻断)
5. ``TemporalGate.check(KO_with_valid_to_before_query_time)`` → warn +
   ``temporal_status:historical`` (spec §10 T-10 — 已过期 → historical, warn 默认
   当前检索不返回)

集成:
- spec §10 全部 11 项规则: T-1 ~ T-11
- A-2 derive_status() (KnowledgeObject.valid_from/valid_to, commit 5 既有)
- A-2 apply_temporal_filter() + _passes_temporal() (默认当前检索)
- 与 Conflict Gate (B-2.8) 协调: temporal 维度由 Conflict Gate 在 6 类冲突中的
  temporal 类接力处理

Ref: docs/architecture/B-2_11_Gate_design.md §3.8 + spec §11.2/§10 + A-2
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.integrity.gates import GateVerdict, TemporalGate


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


@dataclass
class NonTemporalObject:
    """Temporal Gate 不关注的非 KO 对象（无 valid_from/valid_to 字段）."""

    id: str = "x"
    value: int = 42


@dataclass
class TemporalObject:
    """Temporal Gate 测试用的对象（含 valid_from/valid_to 字段, A-2 形态).

    字段:
        id: KO id
        valid_from: spec §10 — knowledge start-of-validity (Unix ms)
        valid_to:   spec §10 — knowledge end-of-validity (Unix ms)
        superseded_by: spec §10 T-3 — 被 supersede 关系 (single id or None)
        supersedes:   spec §10 T-3 — supersede 关系 (single id or None)
    """

    id: str
    valid_from: int | None = None
    valid_to: int | None = None
    superseded_by: str | None = None
    supersedes: str | None = None


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestTemporalGate:
    """spec §11.2 Gate 8: 时间字段自洽，无非法重叠."""

    def test_non_temporal_object_passes(self):
        """非 Temporal 对象（无 valid_from/valid_to 字段，如 WikiPage）→ pass
        (helper: A-2 仅在 KnowledgeObject 加字段, 不在本 Gate 关注范围)."""
        gate = TemporalGate()
        obj = NonTemporalObject(id="x", value=42)

        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ko_with_both_bounds_none_warns(self):
        """KO + valid_from=None + valid_to=None → warn +
        ``unknown_temporal:both_bounds_none``（spec §10 T-2 / T-9 — 缺任一边界
        → unknown 状态; 默认当前检索不返回, 但仅 warn 不阻断发布）."""
        gate = TemporalGate()
        obj = TemporalObject(id="ko_001", valid_from=None, valid_to=None)

        verdict = gate.check(obj)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "unknown_temporal:both_bounds_none" in verdict.reasons

    def test_ko_with_invalid_temporal_blocks(self):
        """KO + valid_from > valid_to → block +
        ``invalid_temporal:valid_from_gt_valid_to``（spec §10 — 时间区间非法
        即阻断默认发布）."""
        gate = TemporalGate()
        # valid_from=200 > valid_to=100 → 非法区间
        obj = TemporalObject(id="ko_002", valid_from=200, valid_to=100)

        verdict = gate.check(obj)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "invalid_temporal:valid_from_gt_valid_to" in verdict.reasons

    def test_ko_with_valid_from_in_future_query_time_in_past_warns_scheduled(self):
        """KO + valid_from 在未来 + query_time 在过去 → warn +
        ``temporal_status:scheduled``（spec §10 T-9 — 未来生效知识,
        scheduled 状态, warn 不阻断)."""
        gate = TemporalGate()
        # valid_from=200 在未来, valid_to=300 → 区间 [200, 300]
        obj = TemporalObject(id="ko_003", valid_from=200, valid_to=300)

        # query_time=100 在过去 → 派生 status=scheduled
        context = {"query_time": 100}
        verdict = gate.check(obj, context=context)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "temporal_status:scheduled" in verdict.reasons

    def test_ko_with_valid_to_before_query_time_warns_historical(self):
        """KO + valid_to 在 query_time 之前 → warn +
        ``temporal_status:historical``（spec §10 T-10 — 已过期知识,
        historical 状态, warn 默认当前检索不返回）."""
        gate = TemporalGate()
        # valid_from=10, valid_to=100 → 区间 [10, 100]
        obj = TemporalObject(id="ko_004", valid_from=10, valid_to=100)

        # query_time=200 在 valid_to=100 之后 → 派生 status=historical
        context = {"query_time": 200}
        verdict = gate.check(obj, context=context)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "temporal_status:historical" in verdict.reasons