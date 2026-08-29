"""Tests for Semantic Support Check (B-1, spec §6 末段 + §11.4 #9 + §A2 Gate).

4 TDD tests for ``src.kc.semantic_support.checker``:

1. ``test_semantic_support_quote_in_block_passes`` — span overlap + matching
   quote → ``supports``.
2. ``test_semantic_support_quote_not_in_block_fails`` — span overlap missing
   (spec §6 末段: 仅 Span 可定位不构成支持) → ``insufficient``.
3. ``test_semantic_support_contradicts`` — quote vs claim 反义词对 → ``contradicts``.
4. ``test_semantic_support_off_by_default`` — ``llm_provider=None`` → no LLM
   calls; ``cost_used_cny == 0``; rule-based fallback.

Until ``src.kc.semantic_support.checker`` ships, every test in this file must
FAIL with ``ImportError`` or ``ModuleNotFoundError``. After B-1 ships, all 4
must pass.

Roadmap v2.2 §B-1:
    spec §6 末段 — Semantic Support Check
    spec §11.4 #9 — Evidence Semantic Support Error = 0
    spec §A2 — Gate SemSupport Accuracy ≥ 0.95
    v2.2 H-3 — ON by default (provider 参数)
    v2.2 H-6 — 50 元/日成本上限 + 抽样 1/10
"""
from __future__ import annotations

import pytest

from src.kc.contracts.evidence import Evidence
from src.kc.semantic_support.checker import (
    SemanticSupportChecker,
    SupportType,
    SupportVerdict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(quote: str, *, evidence_type: str = "direct_quote") -> Evidence:
    """Build a minimal Evidence value for tests (spec §5.7)."""
    return Evidence(
        evidence_id="ev_test_001",
        document_id="doc_test_001",
        block_id="blk_test_001",
        quote=quote,
        evidence_type=evidence_type,
    )


# ---------------------------------------------------------------------------
# Test 1: quote in block (span overlap) → supports
# ---------------------------------------------------------------------------


def test_semantic_support_quote_in_block_passes():
    """Evidence quote 与 claim 有 token 重叠 + 无矛盾 → ``supports``.

    spec §6 末段: span_overlap=True → 蕴含 / 部分支持判定进入 LLM/规则路径。
    这里默认 OFF（无 LLM），应走规则快速判定并返回 supports。
    """
    checker = SemanticSupportChecker()  # llm_provider=None → OFF by default
    evidence = _evidence("Hello world")
    verdict = checker.check(
        evidence=evidence,
        claim_text="The text says hello world",
        claim_id="cl_test_001",
    )

    assert isinstance(verdict, SupportVerdict)
    assert verdict.support_type == "supports"
    assert verdict.span_overlap is True
    assert verdict.evidence_id == "ev_test_001"
    assert verdict.claim_id == "cl_test_001"
    assert verdict.judgment_source == "rule"
    assert verdict.quality_metric_eligible is False
    assert 0.0 <= verdict.confidence <= 1.0


# ---------------------------------------------------------------------------
# Test 2: span overlap missing → insufficient (spec §6 末段)
# ---------------------------------------------------------------------------


def test_semantic_support_quote_not_in_block_fails():
    """Evidence quote 与 claim 完全无 token 重叠 → ``insufficient``。

    spec §6 末段: "仅 Span 可定位不构成支持" — span_overlap=False 即视为
    insufficient（不是 supports）。
    """
    checker = SemanticSupportChecker()
    evidence = _evidence("量子纠缠是物理学现象")
    verdict = checker.check(
        evidence=evidence,
        claim_text="Mitochondria are the powerhouse of the cell",
        claim_id="cl_test_002",
    )

    assert verdict.support_type == "insufficient"
    assert verdict.span_overlap is False
    assert verdict.supports_scope is False
    assert verdict.supports_temporal is False
    assert verdict.judgment_source == "rule"
    assert verdict.quality_metric_eligible is False
    # 置信度应高：判定"不充分"是高置信度的负面结论
    assert verdict.confidence >= 0.5


# ---------------------------------------------------------------------------
# Test 3: contradiction
# ---------------------------------------------------------------------------


def test_semantic_support_contradicts():
    """Evidence quote 与 claim 含反义词对 → ``contradicts``（高置信度）。

    spec §8 末段: 反义词对 → "contradicts" 而非 "irrelevant"。
    """
    checker = SemanticSupportChecker()
    evidence = _evidence("Carbon tax reduces emissions")
    verdict = checker.check(
        evidence=evidence,
        claim_text="Carbon tax increases emissions",
        claim_id="cl_test_003",
    )

    assert verdict.support_type == "contradicts"
    assert verdict.span_overlap is True
    assert verdict.judgment_source == "rule"
    assert verdict.quality_metric_eligible is False
    assert verdict.confidence >= 0.7
    # 矛盾应当附带 reasoning 说明
    assert "矛盾" in verdict.reasoning or "contradict" in verdict.reasoning.lower()


# ---------------------------------------------------------------------------
# Test 4: OFF by default
# ---------------------------------------------------------------------------


def test_semantic_support_off_by_default():
    """``llm_provider=None`` 时: 不调用 LLM + cost_used_cny=0 + 规则 fallback。

    路线 v2.2 H-3 决策: ON by default（提供 llm_provider 接口）,
    但本测试验证默认构造时确实 OFF。spec §6 末段默认行为。
    """
    checker = SemanticSupportChecker()
    assert checker.llm_provider is None
    assert checker.cost_used_cny == 0.0

    # 多次调用后 cost_used_cny 仍为 0（未触发 LLM）
    evidence = _evidence("Some factual claim")
    for _ in range(20):  # 超过 sample_ratio=10 的阈值
        verdict = checker.check(
            evidence=evidence,
            claim_text="Some factual claim about topic",
            claim_id="cl_test_004",
        )
        # 默认 OFF：必须不调用 LLM，cost 恒为 0
        assert checker.cost_used_cny == 0.0

    # 抽样次数累加是 OK 的（属于本地状态），但 cost 必须为 0
    assert verdict is not None
    assert verdict.judgment_source == "rule"
    assert verdict.quality_metric_eligible is False
    assert verdict.support_type in {
        "supports", "partially_supports", "irrelevant",
        "contradicts", "insufficient",
    }


# ---------------------------------------------------------------------------
# Test 5 (bonus, scope of evidence ON path is provided): ON interface exists
# ---------------------------------------------------------------------------


def test_semantic_support_on_provider_interface():
    """``llm_provider="openai"`` 构造时: 接口存在 + 抽样 1/10 后 cost 递增。

    验证 v2.2 H-3 决策: ON by default（提供 llm_provider 接口）;
    H-6 抽样 1/10 + 50 元/日成本上限。
    """
    checker = SemanticSupportChecker(
        llm_provider="openai",
        cost_limit_cny=50.0,
        sample_ratio=10,
    )
    assert checker.llm_provider == "openai"
    assert checker.cost_limit_cny == 50.0
    assert checker.sample_ratio == 10
    assert checker.cost_used_cny == 0.0

    evidence = _evidence("Active span content")
    # 第 1~9 次调用 → 不命中抽样（_should_sample 内部 count 从 0 起）
    # 第 10 次调用 → 命中抽样（count == 10, 10 % 10 == 0）
    for i in range(1, 11):
        verdict = checker.check(
            evidence=evidence,
            claim_text="Active span content appears here",
            claim_id=f"cl_on_{i:03d}",
        )

    # 第 10 次后成本应当 > 0（命中抽样）
    assert checker.cost_used_cny > 0.0, (
        "第 10 次调用应命中 1/10 抽样并触发 LLM mock"
    )
    assert verdict.judgment_source == "mock"
    assert verdict.quality_metric_eligible is False
    # 成本应当远低于上限
    assert checker.cost_used_cny < checker.cost_limit_cny
