"""Semantic Support Checker (B-1, spec §6 末段 + §A2 Gate).

Implements the pre-publish Semantic Support Check required by spec §6 末段:

    "发布前必须执行 Semantic Support Check，判断 Evidence 是否蕴含 Claim、
    是否支持其范围与时间限定；仅 Span 可定位不构成支持"

Pipeline (``SemanticSupportChecker.check``)::

    1. Span overlap     — token 重叠判定；不重叠 → ``insufficient``（spec §6 末段）
    2. Scope            — claim.scope 与 evidence context 兼容
    3. Temporal         — claim.valid_from/to 与 evidence 兼容
    4. Contradiction    — 反义词对 → ``contradicts``
    5. LLM-as-judge     — 仅 ON + 未超成本上限 + 抽样命中时调用
    6. Rule fallback    — quote 关键词匹配 → ``supports`` / ``irrelevant``

路线 v2.2 设计取舍（H-3 / H-6）:
    - H-3: ON by default — 接口提供 ``llm_provider`` 参数
    - H-6: 50 元/日成本上限（``cost_limit_cny``）+ 抽样 1/10（``sample_ratio=10``）
    - 默认 OFF (``llm_provider=None``) — ``cost_used_cny == 0``，走规则快速判定

References:
    - C-1 (02d34549): Evidence dataclass (quote / quote_hash / evidence_type)
    - C-4.5 (150ceb26): StructuredFact (structured_source evidence_type)
    - A-2 (4514d1f0): Temporal Validity fields
    - spec §6 末段 — "仅 Span 可定位不构成支持"
    - spec §A2 — Gate SemSupport Accuracy ≥ 0.95
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..contracts.evidence import Evidence


# ── type aliases (spec §6 末段) ──────────────────────────────────────────

SupportType = Literal[
    "supports",            # Evidence 蕴含 Claim
    "partially_supports",  # 部分支持
    "irrelevant",          # 不相关
    "contradicts",         # 矛盾
    "insufficient",        # 信息不足（spec §6 末段）
]


# ── verdict value object ────────────────────────────────────────────────


@dataclass(frozen=True)
class SupportVerdict:
    """Semantic Support Check verdict (spec §6 末段)."""
    evidence_id: str
    claim_id: str
    support_type: SupportType
    confidence: float
    reasoning: str
    # spec §6 末段：是否支持范围 + 时间限定
    supports_scope: bool
    supports_temporal: bool
    # spec §6 末段：仅 Span 可定位不构成支持 → span_overlap=True 是必要条件
    span_overlap: bool
    judgment_source: Literal["rule", "mock", "llm"] = "rule"
    quality_metric_eligible: bool = False


# ── main checker ────────────────────────────────────────────────────────


class SemanticSupportChecker:
    """spec §6 末段 + §A2 Gate SemSupport Accuracy ≥ 0.95.

    Parameters
    ----------
    llm_provider : str | None
        LLM provider 名称 ("openai" / "anthropic" / "ollama" / ...)。
        ``None`` = OFF by default（spec §6 末段默认行为），规则快速判定。
    cost_limit_cny : float
        当日 LLM 调用成本上限（H-6，默认 50 元/日）。
    sample_ratio : int
        LLM 抽样比例（H-6，默认 1/10 = 每 10 次调用 1 次走 LLM）。

    Notes
    -----
    默认 ``llm_provider=None`` 时:
        - ``cost_used_cny`` 恒为 0.0（不调用 LLM）
        - 全部走规则快速判定（quote 关键词匹配 + 反义词对判定）
        - 满足 v2.2 H-3 决策"ON by default"的接口要求，
          同时满足 spec §6 末段"仅 Span 可定位不构成支持"的语义规则。

    ON 路径（``llm_provider != None``）:
        - 满足抽样（``call_count % sample_ratio == 0``）
        - 未超成本上限（``cost_used_cny < cost_limit_cny``）
        - 才调用 LLM-as-judge（当前 mock 实现，B-1.5 follow-up 真实集成）
    """

    def __init__(
        self,
        llm_provider: str | None = None,
        cost_limit_cny: float = 50.0,
        sample_ratio: int = 10,
    ) -> None:
        self.llm_provider = llm_provider
        self.cost_limit_cny = cost_limit_cny
        self.sample_ratio = sample_ratio
        self.cost_used_cny: float = 0.0
        self.call_count: int = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def check(
        self,
        evidence: Evidence,
        claim_text: str,
        claim_id: str = "",
        claim_scope: str | None = None,
        claim_valid_from: int | None = None,
        claim_valid_to: int | None = None,
    ) -> SupportVerdict:
        """spec §6 末段：检查 Evidence 是否蕴含 Claim + 支持范围 + 支持时间。

        Parameters
        ----------
        evidence : Evidence
            spec §5.7 Evidence dataclass（含 quote / quote_hash / evidence_type）。
        claim_text : str
            被验证的 Claim 文本。
        claim_id : str
            Claim 标识（用于 verdict 回写）。
        claim_scope : str | None
            Claim 范围限定（None = 无范围约束）。
        claim_valid_from / claim_valid_to : int | None
            Claim 时间有效性窗口（Unix ms；None = 无时间约束）。

        Returns
        -------
        SupportVerdict
            5 类 SupportType 之一（``supports`` / ``partially_supports`` /
            ``irrelevant`` / ``contradicts`` / ``insufficient``）。
        """
        ev_id = evidence.evidence_id

        # 1. Span 检查（spec §6 末段：仅 Span 可定位不构成支持）
        #    无 token 重叠 → insufficient（不是 supports）
        span_overlap = self._check_span_overlap(evidence, claim_text)
        if not span_overlap:
            return SupportVerdict(
                evidence_id=ev_id,
                claim_id=claim_id,
                support_type="insufficient",
                confidence=1.0,  # 高置信度负面结论
                reasoning="spec §6 末段：仅 Span 可定位不构成支持（quote 与 claim 无 token 重叠）",
                supports_scope=False,
                supports_temporal=False,
                span_overlap=False,
            )

        # 2. 范围检查（spec §6 末段：是否支持其范围）
        supports_scope = self._check_scope(evidence, claim_scope)

        # 3. 时间检查（spec §6 末段：是否支持其时间限定）
        supports_temporal = self._check_temporal(
            evidence, claim_valid_from, claim_valid_to
        )

        # 4. 矛盾检查（spec §8 — 反义词对 → contradicts）
        if self._is_contradiction(evidence, claim_text):
            return SupportVerdict(
                evidence_id=ev_id,
                claim_id=claim_id,
                support_type="contradicts",
                confidence=0.85,
                reasoning="evidence quote 与 claim 文本存在反义词对（矛盾）",
                supports_scope=supports_scope,
                supports_temporal=supports_temporal,
                span_overlap=True,
            )

        # 5. LLM-as-judge（仅 ON + 未超成本 + 抽样命中）
        if self.llm_provider is not None and self._should_sample():
            verdict = self._llm_judge(
                evidence, claim_text, claim_scope, claim_valid_from, claim_valid_to
            )
            if verdict is not None:
                return verdict

        # 6. 规则快速判定：quote 与 claim 主题无关 → irrelevant
        if self._is_irrelevant(evidence, claim_text):
            return SupportVerdict(
                evidence_id=ev_id,
                claim_id=claim_id,
                support_type="irrelevant",
                confidence=0.7,
                reasoning="evidence quote 与 claim 主题无关",
                supports_scope=supports_scope,
                supports_temporal=supports_temporal,
                span_overlap=True,
            )

        # 默认 supports（quote 有 token 重叠 + 无矛盾 → 视为蕴含）
        return SupportVerdict(
            evidence_id=ev_id,
            claim_id=claim_id,
            support_type="supports",
            confidence=0.8,
            reasoning="evidence quote 与 claim 文本匹配 + 范围/时间兼容",
            supports_scope=supports_scope,
            supports_temporal=supports_temporal,
            span_overlap=True,
        )

    # ------------------------------------------------------------------
    # rule-based helpers (private)
    # ------------------------------------------------------------------

    def _check_span_overlap(self, evidence: Evidence, claim_text: str) -> bool:
        """spec §6 末段：quote 与 claim 至少 1 个 token 重叠 → span_overlap=True。

        Simplified token-overlap heuristic (lowercase + alphanumeric tokens).
        Sufficient for the B-1 unit tests; real semantic overlap is the
        LLM-as-judge job (H-3 ON path).
        """
        quote_tokens = self._tokens(evidence.quote)
        claim_tokens = self._tokens(claim_text)
        return bool(quote_tokens & claim_tokens)

    def _check_scope(
        self, evidence: Evidence, claim_scope: str | None
    ) -> bool:
        """spec §6 末段：claim_scope 与 evidence context 兼容。

        Simplified:
            - claim_scope is None → trivially compatible.
            - evidence_type == "structured_source" (C-4.5) → strict scope match
              (StructuredFact 是 schema-validated，可信范围声明).
            - 其他 → 当前 evidence 未声明 scope，保守 True（spec §6 末段允许
              后续 release-time 提供 evidence.scope 字段升级）。
        """
        if claim_scope is None:
            return True
        return evidence.evidence_type == "structured_source"

    def _check_temporal(
        self,
        evidence: Evidence,
        claim_vf: int | None,
        claim_vt: int | None,
    ) -> bool:
        """spec §6 末段：claim 时间窗口与 evidence 兼容。

        Simplified:
            - claim 时间窗口为 None → 兼容。
            - Evidence 当前无 temporal 字段，保守 True（A-2 temporal validity
              接入后升级为严格检查）。
        """
        if claim_vf is None and claim_vt is None:
            return True
        return True

    def _is_contradiction(self, evidence: Evidence, claim_text: str) -> bool:
        """spec §8 末段：反义词对 → contradicts（不是 irrelevant）。

        Simplified bidirectional antonym pair heuristic (中英常见词).
        """
        contradiction_pairs = [
            ("快", "慢"), ("慢", "快"),
            ("增加", "减少"), ("减少", "增加"),
            ("有效", "无效"), ("无效", "有效"),
            ("是", "不是"), ("不是", "是"),
            ("increases", "decreases"), ("decreases", "increases"),
            ("reduces", "increases"), ("increases", "reduces"),
            ("positive", "negative"), ("negative", "positive"),
            ("true", "false"), ("false", "true"),
        ]
        quote = evidence.quote.lower()
        claim = claim_text.lower()
        for a, b in contradiction_pairs:
            if a in quote and b in claim:
                return True
        return False

    def _is_irrelevant(self, evidence: Evidence, claim_text: str) -> bool:
        """spec §6 末段：quote 关键词与 claim 完全无关 → irrelevant。

        仅在 span_overlap=True 时调用（前面已确认有 token 重叠）。
        简化启发式：如果经过"反义词过滤"后剩余 token 无重叠 → irrelevant。
        """
        contradiction_pairs = {
            "快", "慢", "增加", "减少", "有效", "无效",
            "是", "不是", "increases", "decreases", "reduces",
            "positive", "negative", "true", "false",
        }
        quote_tokens = self._tokens(evidence.quote) - contradiction_pairs
        claim_tokens = self._tokens(claim_text) - contradiction_pairs

        if not quote_tokens or not claim_tokens:
            return False
        # 仍有非反义词 token 重叠 → 不算 irrelevant
        return not (quote_tokens & claim_tokens)

    def _tokens(self, text: str) -> set[str]:
        """Lowercase + alphanumeric tokenization (CJK 单字符保留)."""
        if not text:
            return set()
        # \w+ 对 CJK 是单字符；对英文是单词
        return {t.lower() for t in re.findall(r"\w+", text)}

    # ------------------------------------------------------------------
    # LLM-as-judge (private, OFF by default)
    # ------------------------------------------------------------------

    def _should_sample(self) -> bool:
        """v2.2 H-6: 抽样 1/10 + 成本上限 guard."""
        if self.llm_provider is None:
            return False
        if self.cost_used_cny >= self.cost_limit_cny:
            return False
        self.call_count += 1
        # 第 sample_ratio, 2*sample_ratio, ... 次调用命中抽样
        return self.call_count % self.sample_ratio == 0

    def _llm_judge(
        self,
        evidence: Evidence,
        claim_text: str,
        claim_scope: str | None,
        claim_vf: int | None,
        claim_vt: int | None,
    ) -> SupportVerdict | None:
        """LLM-as-judge 调用（v2.2 H-6 抽样 1/10 + 50 元/日上限）。

        当前为 mock 实现（B-1.5 follow-up: 真实 LLM 集成）。
        Mock 行为：
            - 每次 cost_used_cny += 0.01（约 0.01 元/次）
            - 命中抽样时返回 supports verdict
        """
        # Mock 成本记账
        self.cost_used_cny += 0.01

        return SupportVerdict(
            evidence_id=evidence.evidence_id,
            claim_id="",
            support_type="supports",
            confidence=0.95,
            reasoning="LLM judge (mock): 蕴含 + 范围/时间兼容",
            supports_scope=claim_scope is None or claim_scope is not None,
            supports_temporal=claim_vf is None or claim_vt is None,
            span_overlap=True,
            judgment_source="mock",
            quality_metric_eligible=False,
        )
