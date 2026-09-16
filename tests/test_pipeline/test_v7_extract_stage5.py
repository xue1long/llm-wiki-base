from __future__ import annotations

import pytest

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    fill_slots,
)
from src.pipeline.v7_extract.topic_clusterer import Topic


@pytest.mark.asyncio
async def test_fill_slots_returns_none_on_total_llm_failure() -> None:
    """D7: when the LLM produces an empty response on every retry,
    ``fill_slots`` returns ``None`` rather than a partial page. The
    caller (``extract_pilot``) records this in
    ``failures.filter_failed_topics`` and drops the topic — it never
    reaches Stage 7 with empty slots.

    v2 used to return a page whose slots were all empty / flagged
    needs_review; v3 (this control-plane refactor) replaces that with
    an explicit ``None`` so the failures ledger has a single source of
    truth.
    """
    page = await fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="扩句法通过增加动作、环境和感官细节，让句子更具体。",
        llm=FakeLLMClient(),
    )

    assert page is None


@pytest.mark.asyncio
async def test_fill_slots_accepts_scripted_llm_json_with_evidence() -> None:
    """v3.1: LLM cites evidence by zero-based ``item_index`` integer into
    ``Topic.item_ids``. All five slots cite the lone ``article-1`` item
    (index 0) — the script maps index back to canonical id."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "精确定义", '
        '"characteristics": "核心特征", "examples": "具体例子", '
        '"related_concepts": "相关概念", "references": "来源文章"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "扩句法原文摘录"}, '
        '"characteristics": {"item_index": 0, '
        '"source_text_excerpt": "核心特征原文"}, '
        '"examples": {"item_index": 0, '
        '"source_text_excerpt": "具体例子原文"}, '
        '"related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "相关概念原文"}, '
        '"references": {"item_index": 0, '
        '"source_text_excerpt": "来源文章原文"}}}',
    )

    page = await fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text=(
            "扩句法原文摘录 扩句法让句子更具体。 核心特征原文 具体例子原文 "
            "相关概念原文 来源文章原文"
        ),
        llm=llm,
        item_texts={"article-1": "扩句法通过增加动作、环境和感官细节，让句子更具体。"},
    )

    assert isinstance(page, ConceptPage)
    assert page.slots["definition"] == "精确定义"
    assert page.slots["references"] == "来源文章"
    assert llm.calls[0]["prompt_kind"] == "fill_slots"
    # All five slots cite the known article-1 item -> no needs_review.
    assert page.needs_review_slots == ()
    # ConceptPage.has_evidence is True when every slot has evidence
    # and none are flagged for review.
    assert page.has_evidence is True


@pytest.mark.asyncio
async def test_fill_slots_fills_missing_llm_slots_without_extra_keys() -> None:
    """LLM only provides definition — other slots stay empty/flagged, no
    placeholder text sneaks in via the body."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "只有定义"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "只有定义"}}}',
    )

    page = await fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="扩句法只有定义",
        llm=llm,
        item_texts={"article-1": "扩句法只有定义的内容。"},
    )

    assert page is not None
    assert set(page.slots) == set(CONCEPT_SLOTS)
    # Only the supplied slot carries evidence; the others are flagged.
    assert "definition" not in page.needs_review_slots
    assert set(page.needs_review_slots) <= set(CONCEPT_SLOTS) - {"definition"}
    assert "slot:" not in page.body


@pytest.mark.asyncio
async def test_fill_slots_flags_forbidden_placeholder_as_needs_review() -> None:
    """A slot whose body matches the forbidden placeholder contract is
    never treated as a successful fill — it always raises needs_review."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "需结合原文核对", '
        '"characteristics": "真实特征", '
        '"examples": "来源未提供明确例子", '
        '"related_concepts": "相关概念", '
        '"references": "来源文章"}, '
        '"evidence": {"characteristics": {"item_index": 0, '
        '"source_text_excerpt": "真实特征"}, '
        '"related_concepts": {"item_index": 0, '
        '"source_text_excerpt": "相关概念"}, '
        '"references": {"item_index": 0, '
        '"source_text_excerpt": "来源文章"}}}',
    )

    page = await fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="真实特征 真实文本 真实特征 相关概念 真实来源文章",
        llm=llm,
        item_texts={"article-1": "真实特征 内容"},
    )

    assert page is not None
    assert "definition" in page.needs_review_slots
    assert "examples" in page.needs_review_slots
    # The other slots are evidence-backed.
    assert "characteristics" not in page.needs_review_slots
    assert page.has_evidence is False


# ---------------------------------------------------------------------------
# Task 17: Stage 5B semantic reviewer for HIGH-risk claims
# ---------------------------------------------------------------------------
import json

from src.pipeline.v7_extract.claim import (
    Claim,
    ClaimRisk,
    ClaimSupport,
    EvidenceRef,
)
from src.pipeline.v7_extract.claim_reviewer import review_high_risk_claims


REVIEWER_PROMPT_KIND = "claim_reviewer"


def _ref(item_id: str = "item-1", start: int = 0, end: int = 80) -> EvidenceRef:
    return EvidenceRef(
        item_id=item_id,
        item_index=0,
        span_index=0,
        start_byte=start,
        end_byte=end,
    )


def _high_risk_claim(
    *,
    claim_id: str,
    text: str,
    refs: list[EvidenceRef] | None = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        slot_name="characteristics",
        text=text,
        evidence_refs=refs if refs is not None else [_ref()],
        support=ClaimSupport.SUPPORTED,
        confidence=0.8,
        risk=ClaimRisk.HIGH,
    )


@pytest.mark.asyncio
async def test_reviewer_rejects_contradicted_claim() -> None:
    """数字 claim 被 reviewer 判 CONTRADICTED → support 降为 INSUFFICIENT_EVIDENCE。"""
    llm = FakeLLMClient()
    llm.script(
        REVIEWER_PROMPT_KIND,
        json.dumps(
            {
                "verdicts": [
                    {"claim_id": "claim-num", "verdict": "contradicted", "reason": "evidence says 8%"}
                ]
            }
        ),
    )

    claim = _high_risk_claim(claim_id="claim-num", text="准确率提高 10%")
    result = await review_high_risk_claims(
        [claim],
        source_bytes=b"prefix " + b"\xe5\x87\xba\xe8\xaf\xaf" * 30 + b" suffix",
        llm=llm,
    )

    assert len(result) == 1
    assert result[0].claim_id == "claim-num"
    assert result[0].support is ClaimSupport.INSUFFICIENT_EVIDENCE


@pytest.mark.asyncio
async def test_reviewer_only_invoked_for_high_risk() -> None:
    """LOW-risk claim 不被 LLM 处理；reviewer 只对 HIGH-risk claim 调用 LLM。"""
    llm = FakeLLMClient()
    # Only script ONE response — for the HIGH-risk claim. The LOW-risk claim
    # must not trigger an LLM call at all (otherwise this script is exhausted
    # and the test would fail).
    llm.script(
        REVIEWER_PROMPT_KIND,
        json.dumps(
            {"verdicts": [{"claim_id": "claim-h", "verdict": "supported", "reason": "ok"}]}
        ),
    )

    low = _high_risk_claim(claim_id="claim-l", text="RAG 是一种检索增强生成方法")
    low.risk = ClaimRisk.LOW  # override: not high-risk

    high = _high_risk_claim(claim_id="claim-h", text="准确率提高 10%")

    result = await review_high_risk_claims(
        [low, high],
        source_bytes=b"prefix " + b"\xe5\x87\xba\xe8\xaf\xaf" * 30 + b" suffix",
        llm=llm,
    )

    # Only one LLM call was made (and only for the HIGH-risk claim).
    assert len(llm.calls) == 1
    # The prompt payload the LLM saw must mention the HIGH claim's id but
    # NOT the LOW claim's id (Bounded Evidence Contract §3.2: the LLM only
    # ever sees HIGH-risk evidence excerpts).
    prompt_kind = llm.calls[0]["prompt_kind"]
    assert prompt_kind == REVIEWER_PROMPT_KIND
    # LOW claim's id must not appear in the LLM call record (caller doesn't
    # log the user_prompt verbatim, but FakeLLMClient records lengths only).
    # We re-execute the rendering through a capturing client to assert content.

    # LOW-risk claim keeps its support verbatim; HIGH-risk claim stays
    # SUPPORTED (verdict == supported).
    low_claim = next(c for c in result if c.claim_id == "claim-l")
    high_claim = next(c for c in result if c.claim_id == "claim-h")
    assert low_claim.support is ClaimSupport.SUPPORTED
    assert high_claim.support is ClaimSupport.SUPPORTED


class _CapturingLLM(FakeLLMClient):
    """FakeLLMClient that also keeps the rendered prompt bodies (Task 15
    established this pattern)."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[tuple[str, str]] = []

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        self.prompts.append((system_prompt, user_prompt))
        return await super().complete(
            prompt_kind=prompt_kind,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )


@pytest.mark.asyncio
async def test_reviewer_only_invoked_for_high_risk_content_check() -> None:
    """Stronger content check for the LOW-bypass invariant: the LLM prompt
    body must literally not contain the LOW claim's text or id."""
    llm = _CapturingLLM()
    llm.script(
        REVIEWER_PROMPT_KIND,
        json.dumps(
            {"verdicts": [{"claim_id": "claim-h", "verdict": "supported", "reason": "ok"}]}
        ),
    )

    low = _high_risk_claim(claim_id="claim-l", text="RAG 是一种检索增强生成方法")
    low.risk = ClaimRisk.LOW
    high = _high_risk_claim(claim_id="claim-h", text="准确率提高 10%")

    await review_high_risk_claims(
        [low, high],
        source_bytes=b"prefix " + b"\xe5\x87\xba\xe8\xaf\xaf" * 30 + b" suffix",
        llm=llm,
    )

    assert len(llm.prompts) == 1
    _, user_prompt = llm.prompts[0]
    assert "claim-h" in user_prompt
    assert "准确率提高 10%" in user_prompt
    # LOW claim's id and distinctive text must not appear in the prompt.
    assert "claim-l" not in user_prompt
    assert "RAG 是一种检索增强生成方法" not in user_prompt


class _ExplodingLLM(FakeLLMClient):
    """FakeLLMClient that always raises LLMResponseError (no scripted
    responses — the queue is empty)."""

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        from src.pipeline.v7_extract.prompts.renderer import LLMResponseError

        raise LLMResponseError("reviewer LLM exploded")


@pytest.mark.asyncio
async def test_reviewer_failure_demotes_claim_to_insufficient() -> None:
    """reviewer 整体失败 → 所有 high-risk claim 降级 INSUFFICIENT（fail-closed）。"""
    llm = _ExplodingLLM()

    claims = [
        _high_risk_claim(claim_id="claim-1", text="准确率提高 10%"),
        _high_risk_claim(claim_id="claim-2", text="导致收敛变慢"),
        _high_risk_claim(claim_id="claim-3", text="不适用于小数据集"),
    ]

    result = await review_high_risk_claims(
        claims,
        source_bytes=b"prefix " + b"\xe5\x87\xba\xe8\xaf\xaf" * 30 + b" suffix",
        llm=llm,
    )

    assert len(result) == 3
    assert all(c.support is ClaimSupport.INSUFFICIENT_EVIDENCE for c in result)
    # Reviewer-level failure must not raise — it returns claims with
    # support downgraded (Failure Contract §1: a technical failure never
    # silently inflates apparent support).
