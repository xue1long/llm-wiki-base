"""Tests for KnowledgeUnit.resolution_event_id field (B-2.5 commit 1 — spec §4.4 + §5.11).

路线 v2.2 §B-2.5 — 关闭 B-2.4 Identity Gate known_limitations:
    "拆分/合并决策应写入 ResolutionEvent——当前 KnowledgeUnit 未实现此字段"

TDD coverage (3 tests):
1. ``KnowledgeUnit(ku_id=..., ..., resolution_event_id="rev_001")`` 构造成功 + 字段读取正确
   (正路: 拆分/合并决策落地后, KU 关联 ResolutionEvent)
2. ``KnowledgeUnit`` 默认 ``resolution_event_id is None`` (back-compat: 既有测试不破坏)
3. ``KnowledgeUnit(ku_id=..., ..., resolution_event_id=None)`` 与不设字段等价
   (反序列化场景: dict.get("resolution_event_id") 自然为 None)

集成:
- A-1 commit 2 scripts/kc_record_resolution_event.py 提供 record_event() +
  make_event_from_split_decision() + make_event_from_merge_decision() —
  KU 通过 resolution_event_id 字段关联 ResolutionEvent
- B-2.4 Identity Gate 留下的 known_limitations "拆分/合并决策应写入 ResolutionEvent"
  现在可解除 (B-2.5 commit 2 GranularityGate 集成)

Ref: docs/architecture/B-2_11_Gate_design.md §3.6 + spec §11.2/§4.2/§4.4/§5.11
"""
from __future__ import annotations

from src.kc.domain import KnowledgeUnit


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


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestResolutionEventIdField:
    """spec §4.4 + §5.11: KnowledgeUnit 必须能关联 ResolutionEvent."""

    def test_ku_with_resolution_event_id_constructs_and_reads(self):
        """KU(resolution_event_id="rev_001") 构造成功 + 字段读取正确 (正路)."""
        ku = _make_ku(resolution_event_id="rev_001")

        assert ku.resolution_event_id == "rev_001"

    def test_ku_default_resolution_event_id_is_none(self):
        """默认 resolution_event_id is None — 既有 14 字段 0 改动 + back-compat."""
        ku = _make_ku()

        assert ku.resolution_event_id is None

    def test_ku_explicit_none_resolution_event_id_equals_default(self):
        """KU(resolution_event_id=None) 与不设字段等价 — 反序列化场景 (back-compat)."""
        ku_explicit = _make_ku(resolution_event_id=None)
        ku_default = _make_ku()

        # 二者等价: 同一字段同值, 同一 identity_key
        assert ku_explicit.resolution_event_id == ku_default.resolution_event_id
        assert ku_explicit.identity_key == ku_default.identity_key
