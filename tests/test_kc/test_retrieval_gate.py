"""Tests for Retrieval Gate (B-2.9 — spec §11.2 Gate 11 + §12.1 默认检索过滤器).

路线 v2.2 §B-2.9 — Retrieval Gate 完整实现.

TDD coverage (5 tests):
1. ``RetrievalGate.check(WikiPage_with_workflow_state_verified)`` → pass
   (spec §11.3 #1 + §12.1 happy path)
2. ``RetrievalGate.check(WikiPage_with_workflow_state_draft)`` → block +
   ``not_verified:workflow_state=draft`` (spec §12.1 默认当前检索过滤器)
3. ``RetrievalGate.check(WikiPage_with_workflow_state_verified_but_temporal_historical)``
   → warn + ``temporal_historical`` (spec §10 T-10 — 已过期知识, 默认当前检索不返回)
4. ``RetrievalGate.check(WikiPage_with_workflow_state_verified_and_temporal_scheduled)``
   → warn + ``temporal_scheduled`` (spec §10 T-9 — 未来生效知识, 默认当前检索不返回)
5. ``RetrievalGate.check(KnowledgeObject_no_workflow_state)`` → pass
   (helper: KnowledgeObject 无 workflow_state 字段 — 不在本 Gate 关注范围)

集成:
- spec §11.2 Gate 11: 发布对象可按 ID、主题和证据链检索
- spec §12.1 默认当前检索过滤器 (4 条件 AND):
  * status = verified (C-2 DefaultFilter workflow_state 维度)
  * temporal_status = current (A-2 derive_status 内联简化)
  * 边界校验 (valid_from <= query_time < valid_to)
  * 显式 include_unknown=true 时返回 unknown (T-7)
- C-2 DefaultFilter (workflow_state 维度, 既有 src/kc/retrieval/filter.py)
- A-2 derive_status (temporal 维度, 既有 src/kc/compiler/temporal.py)
- B-1 SemanticSupportChecker (evidence 维度, 既有 — 默认 OFF)

Ref: docs/architecture/B-2_11_Gate_design.md §3.11 + spec §11.2/§12.1
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from src.kc.integrity.gates import RetrievalGate
from src.wiki.core.types import PageType, WikiPage


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


def _now_ms() -> int:
    """Return the current Unix time in milliseconds."""
    return int(time.time() * 1000)


def make_wiki_page(
    workflow_state: str = "draft",
    id: str = "test_001",
    **kwargs,
) -> WikiPage:
    """Build a test WikiPage with the given workflow_state.

    WikiPage 原生没有 valid_from / valid_to 字段 — Retrieval Gate 测试需要
    时序维度校验时, 通过 setattr 注入这两个字段 (与 C-2 DefaultFilter
    自定义生命周期注入模式一致).
    """
    page = WikiPage(
        id=id,
        title=kwargs.get("title", "test"),
        type=PageType(kwargs.get("type", "concept")),
    )
    page.workflow_state = workflow_state
    # 注入 valid_from / valid_to (如提供)
    if "valid_from" in kwargs:
        page.valid_from = kwargs["valid_from"]
    if "valid_to" in kwargs:
        page.valid_to = kwargs["valid_to"]
    return page


@dataclass
class KnowledgeObjectNoWorkflowState:
    """Retrieval Gate 不关注的非 WikiPage 对象 (无 workflow_state 字段).

    KnowledgeObject 形态 (B-2.x): 仅有 valid_from/valid_to (A-2 既有),
    无 workflow_state — Retrieval Gate 仅在 workflow_state 字段存在时
    启用默认当前检索过滤 (helper: 不适用场景).
    """

    id: str = "ko_001"
    valid_from: int | None = None
    valid_to: int | None = None


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestRetrievalGate:
    """spec §11.2 Gate 11: 发布对象可按 ID、主题和证据链检索."""

    def test_wiki_page_verified_passes(self):
        """WikiPage workflow_state = verified + query_time 在边界内 → pass
        (spec §11.3 #1 + §12.1 happy path — 默认当前检索过滤器通过)."""
        gate = RetrievalGate()
        page = make_wiki_page(workflow_state="verified", id="wp_verified")

        verdict = gate.check(page, context={"query_time": _now_ms()})

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_wiki_page_draft_blocks(self):
        """WikiPage workflow_state = draft → block +
        ``not_verified:workflow_state=draft`` (spec §12.1 默认当前检索过滤器
        — 非 verified 状态阻断默认检索)."""
        gate = RetrievalGate()
        page = make_wiki_page(workflow_state="draft", id="wp_draft")

        verdict = gate.check(page, context={"query_time": _now_ms()})

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "not_verified:workflow_state=draft" in verdict.reasons

    def test_wiki_page_verified_but_temporal_historical_warns(self):
        """WikiPage workflow_state = verified 但 valid_to 在 query_time 之前 →
        warn + ``temporal_historical`` (spec §10 T-10 — 已过期知识,
        默认当前检索不返回, warn 不阻断发布)."""
        gate = RetrievalGate()
        now = _now_ms()
        # valid_from=10, valid_to=100 → 区间 [10, 100] (远早于 now)
        page = make_wiki_page(
            workflow_state="verified",
            id="wp_historical",
            valid_from=10,
            valid_to=100,
        )

        # query_time=now > valid_to=100 → 派生 status=historical
        verdict = gate.check(page, context={"query_time": now})

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "temporal_historical" in verdict.reasons

    def test_wiki_page_verified_and_temporal_scheduled_warns(self):
        """WikiPage workflow_state = verified 但 valid_from 在 query_time 之后 →
        warn + ``temporal_scheduled`` (spec §10 T-9 — 未来生效知识,
        默认当前检索不返回, warn 不阻断发布)."""
        gate = RetrievalGate()
        now = _now_ms()
        # valid_from=now+1d, valid_to=now+30d → 区间 [now+1d, now+30d] (未来)
        page = make_wiki_page(
            workflow_state="verified",
            id="wp_scheduled",
            valid_from=now + 86400000,  # +1 day
            valid_to=now + 2592000000,   # +30 days
        )

        # query_time=now < valid_from → 派生 status=scheduled
        verdict = gate.check(page, context={"query_time": now})

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "temporal_scheduled" in verdict.reasons

    def test_knowledge_object_no_workflow_state_passes(self):
        """KnowledgeObject 形态 (无 workflow_state 字段, 仅有 valid_from /
        valid_to) → pass (helper: 不在本 Gate 关注范围 — KnowledgeObject 由
        Context/Temporal/Conflict Gate 处理, Retrieval Gate 仅在
        WikiPage 类对象上启用默认当前检索过滤)."""
        gate = RetrievalGate()
        obj = KnowledgeObjectNoWorkflowState(id="ko_001")

        verdict = gate.check(obj, context={"query_time": _now_ms()})

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False
