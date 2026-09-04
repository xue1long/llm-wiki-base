"""Tests for Context Gate (B-2.6 — spec §11.2 Gate 7 + §5.1 Context + §8.3 5 匹配语义).

路线 v2.2 §B-2.6 — Context Gate 完整实现.

TDD coverage (5 tests):
1. ``ContextGate.check(obj_without_context_attr)`` → pass (helper: 非 KC 对象不适用)
2. ``ContextGate.check(KO_with_full_context_all_decisive_dimensions_known)`` → pass
   (spec §5.1 8 维度全填 + 决定性维度已知)
3. ``ContextGate.check(KO_with_unknown_domain_decisive)`` → warn +
   ``unknown_decisive_dimension:domain`` (spec §8.2 X-9 — 任一决定性维度 unknown
   + 潜在互斥 → unresolved 类，Context Gate 阶段先 warn)
4. ``ContextGate.check(KO_with_missing_candidate_b_context)`` → block +
   ``missing_candidate_b_context`` (spec §8.3 — 候选比较对象 context 缺失即阻断)
5. ``ContextGate.check(WikiPage_with_category_but_no_context_domain)`` → warn +
   ``missing_domain_from_k5_taxonomy`` (K-5 加固 — WikiPage.category → Context.domain
   必填映射)

集成:
- spec §5.1 Context 8 维度 (domain/platform/audience/geography/language/
  goal/conditions/perspective) — 决定性 5 维度: domain/platform/audience/
  geography/language
- spec §8.3 5 匹配语义 (exact/compatible/disjoint/unresolved/ignored)
- spec §8.2 X-9: 任一决定性维度 unknown + 潜在互斥 → unresolved 类
- A-3 ConflictClassifier 6 类型 (actual/conditional/temporal/perspective/none/
  unresolved) — Context Gate 不直接调用，仅集成 _has_unknown_dimension
  判定思路；与 Conflict Gate (B-2.8) 接力：Conflict Gate 才真正分类为 unresolved
- K-5 Taxonomy 映射: WikiPage.category → Context.domain，WikiPage.taxonomy_sub
  → Context.platform

Ref: docs/architecture/B-2_11_Gate_design.md §3.7 + spec §11.2/§5.1/§8.2/§8.3
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.integrity.gates import ContextGate


# ─── 测试夹具 ─────────────────────────────────────────────────────────────


@dataclass
class NonContextObject:
    """Context Gate 不关注的非 KC 对象（无 context 字段）."""

    id: str = "x"
    value: int = 42


@dataclass
class ContextObject:
    """Context Gate 测试用的对象（包含 context 字段 + K-5 兼容路径).

    字段:
        context: spec §5.1 Context 8 维度 dict
        category: WikiPage 兼容 — K-5 加固: WikiPage.category → Context.domain
        taxonomy_sub: WikiPage 兼容 — K-5 加固: WikiPage.taxonomy_sub → Context.platform
    """

    id: str
    context: dict | None = None
    category: str = ""
    taxonomy_sub: str = ""


def _make_full_context() -> dict:
    """spec §5.1 Context 8 维度全填 + 决定性 5 维度已知."""
    return {
        "domain": "natural_science",
        "platform": "wikipedia",
        "audience": "researchers",
        "geography": "global",
        "language": "zh",
        "goal": "definition",
        "conditions": "ambient",
        "perspective": "neutral",
    }


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestContextGate:
    """spec §11.2 Gate 7: 适用范围明确或标记 unknown."""

    def test_non_context_object_passes(self):
        """非 KC 对象（无 context 字段）→ pass（helper: 不在本 Gate 关注范围）."""
        gate = ContextGate()
        obj = NonContextObject(id="x", value=42)

        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ko_with_full_context_passes(self):
        """KO 含 spec §5.1 完整 Context 8 维度 + 决定性维度全填 → pass."""
        gate = ContextGate()
        obj = ContextObject(id="ko_001", context=_make_full_context())

        verdict = gate.check(obj)

        assert verdict.passed is True
        assert verdict.severity == "info"
        assert verdict.blocked is False

    def test_ko_with_unknown_domain_decisive_warns(self):
        """KO Context 中决定性维度 domain = 'unknown' → warn +
        ``unknown_decisive_dimension:domain``（spec §8.2 X-9 + §5.1 决定性维度）.

        实际阻断由 Conflict Gate (B-2.8) 在 unresolved 类下处理；Context Gate
        阶段仅记录 warn（不阻断，但留痕）。"""
        gate = ContextGate()
        ctx = _make_full_context()
        ctx["domain"] = "unknown"  # 决定性维度 unknown
        obj = ContextObject(id="ko_002", context=ctx)

        verdict = gate.check(obj)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "unknown_decisive_dimension:domain" in verdict.reasons

    def test_ko_with_missing_candidate_b_context_blocks(self):
        """KO + context[\"candidate_b_context\"] = None → block +
        ``missing_candidate_b_context``（spec §8.3 — 候选比较对象 context
        缺失，无法判定匹配语义，阻断默认发布）."""
        gate = ContextGate()
        obj = ContextObject(id="ko_003", context=_make_full_context())

        # context 传入 candidate_b_context = None → 阻断
        ctx = {"candidate_b_context": None}

        verdict = gate.check(obj, context=ctx)

        assert verdict.passed is False
        assert verdict.severity == "block"
        assert verdict.blocked is True
        assert "missing_candidate_b_context" in verdict.reasons

    def test_wiki_page_with_category_but_no_context_domain_warns(self):
        """WikiPage 含 category 但 Context 缺 domain → warn +
        ``missing_domain_from_k5_taxonomy``（K-5 加固: WikiPage.category →
        Context.domain 必填映射，否则进默认检索时 dimension 缺失）."""
        gate = ContextGate()
        # WikiPage 形态 — category 有值, context 有但缺 domain
        obj = ContextObject(
            id="wp_001",
            context={"platform": "wikipedia"},  # 缺 domain
            category="natural_science",  # K-5 映射源
        )

        verdict = gate.check(obj)

        assert verdict.passed is True  # warn 不阻断
        assert verdict.severity == "warn"
        assert "missing_domain_from_k5_taxonomy" in verdict.reasons
