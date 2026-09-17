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
    ``Topic.item_ids``. All eight slots cite the lone ``article-1`` item
    (index 0) — the script maps index back to canonical id."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "精确定义", '
        '"characteristics": "核心特征", '
        '"context": "适用场景", '
        '"anti_patterns": "反模式", '
        '"evidence": "证据强度", '
        '"examples": "具体例子", '
        '"related_concepts": "相关概念", "references": "来源文章"}, '
        '"evidence": {"definition": {"item_index": 0, '
        '"source_text_excerpt": "扩句法原文摘录"}, '
        '"characteristics": {"item_index": 0, '
        '"source_text_excerpt": "核心特征原文"}, '
        '"context": {"item_index": 0, '
        '"source_text_excerpt": "适用场景原文"}, '
        '"anti_patterns": {"item_index": 0, '
        '"source_text_excerpt": "反模式原文"}, '
        '"evidence": {"item_index": 0, '
        '"source_text_excerpt": "证据强度原文"}, '
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
            "扩句法原文摘录 扩句法让句子更具体。 核心特征原文 适用场景原文 "
            "反模式原文 证据强度原文 具体例子原文 相关概念原文 来源文章原文"
        ),
        llm=llm,
        item_texts={"article-1": "扩句法通过增加动作、环境和感官细节，让句子更具体。"},
    )

    assert isinstance(page, ConceptPage)
    assert page.slots["definition"] == "精确定义"
    assert page.slots["references"] == "来源文章"
    assert llm.calls[0]["prompt_kind"] == "fill_slots"
    # All eight slots cite the known article-1 item -> no needs_review.
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


# ---------------------------------------------------------------------------
# Task 18: Stage 5B deterministic page synthesis + FillResult
# ---------------------------------------------------------------------------

from src.pipeline.v7_extract.page_synthesizer import (
    FillResult,
    FillStatus,
    map_fill_to_extraction,
    synthesize_slot,
)
from src.pipeline.v7_extract.failures import ExtractionStatus


def _make_supported_claim(
    *,
    claim_id: str,
    slot_name: str,
    text: str,
    refs: list[EvidenceRef] | None = None,
) -> Claim:
    """Build a SUPPORTED claim carrying at least one evidence ref by default.

    Used to exercise ``synthesize_slot`` and ``FillResult`` rendering. Refs
    default to one valid EvidenceRef so the claim passes
    ``filter_substantive_claims``.
    """
    return Claim(
        claim_id=claim_id,
        slot_name=slot_name,
        text=text,
        evidence_refs=refs if refs is not None else [_ref()],
        support=ClaimSupport.SUPPORTED,
        confidence=0.9,
        risk=ClaimRisk.LOW,
    )


def test_synthesize_slot_drops_unsupported_claims() -> None:
    """``synthesize_slot`` 只保留 SUPPORTED + 有 evidence 的 claim。

    Output format: bullet list (one bullet per SUPPORTED claim, deterministic
    order). Empty input -> empty body so the caller marks the slot as
    needs_review. INSUFFICIENT_EVIDENCE claims (and SUPPORTED claims with
    no evidence) MUST NOT appear in the rendered Markdown — that is the
    last mechanical gate before publication.
    """
    good1 = _make_supported_claim(
        claim_id="claim-a", slot_name="definition", text="概念是…",
    )
    good2 = _make_supported_claim(
        claim_id="claim-b", slot_name="definition", text="特征是…",
    )
    insufficient = _make_supported_claim(
        claim_id="claim-c", slot_name="definition", text="应该被丢弃",
    )
    insufficient.support = ClaimSupport.INSUFFICIENT_EVIDENCE
    no_evidence = Claim(
        claim_id="claim-d", slot_name="definition", text="没有证据",
        evidence_refs=[],
        support=ClaimSupport.SUPPORTED,
    )

    body = synthesize_slot("definition", [good1, insufficient, good2, no_evidence])

    # Two SUPPORTED claims => two bullet items (deterministic input order).
    assert body.count("- 概念是") == 1
    assert body.count("- 特征是") == 1
    assert body.count("- 应该被丢弃") == 0
    assert body.count("- 没有证据") == 0
    # Sentence-final "。" preservation / appending: claim texts above already
    # end with "…" (not "。") so the renderer appends "。" exactly once per
    # bullet — verify by counting the trailing punctuation per bullet line.
    lines = [line for line in body.splitlines() if line.startswith("- ")]
    assert len(lines) == 2
    assert all(line.endswith("。") for line in lines)

    # Empty input -> empty body (caller marks slot needs_review).
    assert synthesize_slot("definition", []) == ""
    # All-unsupported input -> empty body too.
    assert synthesize_slot("definition", [insufficient, no_evidence]) == ""


def test_fillresult_status_mapping_to_extraction() -> None:
    """``FillStatus`` → ``ExtractionStatus`` 五态映射（硬指标：TECHNICAL_FAILURE → FAILED）。

    Six cases from the spec:
      TECHNICAL_FAILURE → FAILED       (关键回归：never WRITTEN)
      INSUFFICIENT      → BLOCKED
      COHERENCE_FAILED  → BLOCKED
      FILLED            → WRITTEN
      PARTIAL >=0.4     → WRITTEN
      PARTIAL <0.4      → BLOCKED

    Plus CONFLICTING with/without the completion_ratio gate to verify both
    branches of the same switch.
    """
    def _make_result(status: FillStatus, completion: float = 1.0) -> FillResult:
        return FillResult(
            topic_id="t",
            title="T",
            status=status,
            slots={},
            needs_review_slots=(),
            metrics={
                "topic_completion_ratio": completion,
                "claim_support_ratio": 1.0,
                "reviewer_verdicts_count": 0,
            },
            generator_fingerprint="",
        )

    # TECHNICAL_FAILURE -> FAILED (hard contract).
    assert (
        map_fill_to_extraction(_make_result(FillStatus.TECHNICAL_FAILURE))
        is ExtractionStatus.FAILED
    )
    # INSUFFICIENT -> BLOCKED.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.INSUFFICIENT))
        is ExtractionStatus.BLOCKED
    )
    # COHERENCE_FAILED -> BLOCKED.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.COHERENCE_FAILED))
        is ExtractionStatus.BLOCKED
    )
    # FILLED -> WRITTEN.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.FILLED))
        is ExtractionStatus.WRITTEN
    )
    # PARTIAL with completion_ratio >= 0.4 -> WRITTEN.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.PARTIAL, completion=0.4))
        is ExtractionStatus.WRITTEN
    )
    assert (
        map_fill_to_extraction(_make_result(FillStatus.PARTIAL, completion=0.8))
        is ExtractionStatus.WRITTEN
    )
    # PARTIAL with completion_ratio < 0.4 -> BLOCKED.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.PARTIAL, completion=0.2))
        is ExtractionStatus.BLOCKED
    )
    # CONFLICTING: same completion_ratio gate as PARTIAL.
    assert (
        map_fill_to_extraction(_make_result(FillStatus.CONFLICTING, completion=0.5))
        is ExtractionStatus.WRITTEN
    )
    assert (
        map_fill_to_extraction(_make_result(FillStatus.CONFLICTING, completion=0.1))
        is ExtractionStatus.BLOCKED
    )


@pytest.mark.asyncio
async def test_legacy_concept_page_still_generated_for_stage7() -> None:
    """``fill_slots``（legacy 入口）仍可用，``fill_slots_v2``（v2 入口）桥接后回填
    ``FillResult.legacy_page``，保证 Stage 7 wiki_writer 的数据契约不破。

    这里只验证 v2 入口能产出 ``FillResult`` 且 ``legacy_page`` 是同标题的
    ``ConceptPage``；不验证内容正确性（fill_slots 的内容正确性已由旧测试
    覆盖）。脚本策略：分别 script ``fill_slots``（legacy）和
    ``fill_slots_extract``（v2 Stage 5A）两种 prompt_kind —— fill_slots
    的脚本会被 legacy fallback 消耗（因为 v2 主路径也要桥接回 legacy
    一次以填充 ConceptPage），fill_slots_extract 的脚本被 Stage 5A 消
    耗，claim_reviewer 不被调用（无 HIGH-risk claim）。要求 LLM 至少能
    提供 definition 的内容以让 FILLED / PARTIAL 状态成立。
    """
    llm = FakeLLMClient()

    # v2 main path -> Stage 5A claim extraction per slot (one claim per slot,
    # all LOW-risk so the reviewer is never invoked). We script 5 responses
    # because fill_slots_v2 calls extract_slot_claims once per slot.
    _claim_payload = json.dumps(
        {
            "claims": [
                {
                    "text": "扩句法是文学创作的具体方法",
                    "span_ids": ["span-stub"],
                    "confidence": 0.9,
                }
            ]
        }
    )
    for slot_name in CONCEPT_SLOTS:
        llm.script("fill_slots_extract", _claim_payload)

    # v2 main path also bridges to legacy fill_slots (for FillResult.legacy_page).
    llm.script(
        "fill_slots",
        json.dumps(
            {
                "slots": {
                    "definition": "扩句法是文学创作的具体方法",
                    "characteristics": "扩句法的特征",
                    "examples": "扩句法例子",
                    "related_concepts": "相关概念",
                    "references": "来源文章",
                },
                "evidence": {
                    "definition": {"item_index": 0, "source_text_excerpt": "扩句法"},
                    "characteristics": {"item_index": 0, "source_text_excerpt": "特征"},
                    "examples": {"item_index": 0, "source_text_excerpt": "例子"},
                    "related_concepts": {"item_index": 0, "source_text_excerpt": "相关"},
                    "references": {"item_index": 0, "source_text_excerpt": "来源"},
                },
            }
        ),
    )

    from src.pipeline.v7_extract.canonical_spans import CanonicalSpan
    # Import inside the test: ``test_v7_extract_feature_flag`` purges
    # ``sys.modules['src.pipeline.v7_extract.*']`` which would otherwise
    # leave this test with a stale ``FillResult`` / ``ConceptPage`` class
    # reference and a mismatch against the freshly imported
    # ``fill_slots_v2`` return value. Re-importing on every call sidesteps
    # the pytest ordering hazard.
    from src.pipeline.v7_extract.page_synthesizer import (
        FillResult as _FillResult,
        fill_slots_v2,
    )
    from src.pipeline.v7_extract.slot_filler import (
        ConceptPage as _ConceptPage,
        fill_slots as _fill_slots,
    )
    from src.pipeline.v7_extract.segmentation import CanonicalItem, ItemKind

    # Minimal CanonicalItem / CanonicalSpan fixture (span byte length = 60,
    # comfortably inside 30..3000).
    item_text = "扩句法原文摘录扩句法让句子更具体" * 2  # 16 CJK chars * 3B = 96B
    item = CanonicalItem(
        item_id="article-1",
        kind=ItemKind.ARTICLE,
        start_byte=0,
        end_byte=len(item_text.encode("utf-8")),
        title="扩句法",
        text=item_text,
    )
    span = CanonicalSpan(
        span_id="span-stub",
        item_id="article-1",
        item_index=0,
        start_byte=0,
        end_byte=item.end_byte,
        char_start=0,
        char_end=len(item_text),
    )
    source_bytes = item_text.encode("utf-8")

    from src.pipeline.v7_extract.topic_clusterer import Topic

    topic = Topic("topic-1", "扩句法", ["article-1"])
    spans_per_slot: dict[str, list[CanonicalSpan]] = {name: [span] for name in CONCEPT_SLOTS}

    result = await fill_slots_v2(
        topic,
        spans_per_slot=spans_per_slot,
        topic_items=[item],
        source_bytes=source_bytes,
        llm=llm,
    )

    # v2 must always return a FillResult, never raise (Failure Contract §1.3).
    assert isinstance(result, _FillResult)
    # legacy bridge must populate FillResult.legacy_page for Stage 7 callers.
    assert isinstance(result.legacy_page, _ConceptPage)
    assert result.legacy_page.title == "扩句法"
    # Stage 5A produced 1 SUPPORTED LOW-risk claim → all 5 slots get that
    # single bullet. Status is PARTIAL (only 1 claim, but body non-empty in
    # all 5 slots via synthesize_slot's deterministic broadcast), metrics
    # recorded, fingerprint present.
    assert result.status in {FillStatus.PARTIAL, FillStatus.FILLED}
    assert result.metrics["topic_completion_ratio"] > 0
    assert result.generator_fingerprint != ""

    # Legacy fill_slots still works (back-compat Acceptance from spec) —
    # use a fresh LLM so the v2 path's scripted responses don't get
    # double-consumed by the legacy call.
    legacy_llm = FakeLLMClient()
    legacy_llm.script(
        "fill_slots",
        json.dumps(
            {
                "slots": {
                    "definition": "legacy 定义",
                    "characteristics": "legacy 特征",
                    "examples": "legacy 例子",
                    "related_concepts": "legacy 相关",
                    "references": "legacy 来源",
                },
                "evidence": {
                    "definition": {"item_index": 0, "source_text_excerpt": "定义"},
                    "characteristics": {"item_index": 0, "source_text_excerpt": "特征"},
                    "examples": {"item_index": 0, "source_text_excerpt": "例子"},
                    "related_concepts": {"item_index": 0, "source_text_excerpt": "相关"},
                    "references": {"item_index": 0, "source_text_excerpt": "来源"},
                },
            }
        ),
    )
    legacy_page = await _fill_slots(
        topic,
        source_text=item_text,
        llm=legacy_llm,
        item_texts={"article-1": item_text},
    )
    assert isinstance(legacy_page, _ConceptPage)
    assert legacy_page.title == "扩句法"


# ---------------------------------------------------------------------------
# Task 38: reviewer cache (avoid re-reviewing identical claim+evidence pairs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewer_cache_hit_skips_llm(tmp_path):
    """Cache fully hit → no LLM call (FakeLLMClient.calls stays empty)."""
    from src.pipeline.v7_extract.claim import Claim, ClaimRisk, ClaimSupport
    from src.pipeline.v7_extract.claim_reviewer import (
        ReviewerCache, ReviewerCacheEntry, review_high_risk_claims,
    )

    ref = type("Ref", (), {"item_id": "i1", "start_byte": 0, "end_byte": 100})()
    claim = Claim(
        claim_id="claim-cache-1",
        slot_name="definition",
        text="X 提高 10%",
        evidence_refs=[ref],
        support=ClaimSupport.SUPPORTED,
        confidence=0.9,
        risk=ClaimRisk.HIGH,
    )

    cache = ReviewerCache(tmp_path)
    # Pre-seed cache for this exact claim.
    key = ReviewerCache.cache_key(claim.text, claim.evidence_refs, "claim_reviewer|v1")
    cache.put(ReviewerCacheEntry(
        cache_key=key, claim_id="claim-cache-1",
        verdict="supported", confidence=0.9, reason="",
        reviewed_at_ms=1_700_000_000_000,
    ))

    fake = FakeLLMClient()
    # No script() — any LLM call would raise KeyError.
    out = await review_high_risk_claims(
        [claim], source_bytes=b"x" * 1000,
        llm=fake, project_root=None, cache=cache,
    )
    assert out[0].support is ClaimSupport.SUPPORTED
    # LLM was NOT called.
    assert fake.calls == []


@pytest.mark.asyncio
async def test_reviewer_cache_miss_falls_back_to_llm(tmp_path):
    """Different evidence → cache miss → LLM runs and verdict persisted."""
    from src.pipeline.v7_extract.claim import Claim, ClaimRisk, ClaimSupport
    from src.pipeline.v7_extract.claim_reviewer import (
        ReviewerCache, ReviewerCacheEntry, review_high_risk_claims,
    )

    ref_a = type("Ref", (), {"item_id": "i1", "start_byte": 0, "end_byte": 100})()
    ref_b = type("Ref", (), {"item_id": "i1", "start_byte": 0, "end_byte": 200})()
    claim = Claim(
        claim_id="claim-cache-miss",
        slot_name="definition",
        text="Y 增加 20%",
        evidence_refs=[ref_b],      # different from ref_a
        support=ClaimSupport.SUPPORTED,
        confidence=0.8,
        risk=ClaimRisk.HIGH,
    )

    cache = ReviewerCache(tmp_path)
    # Seed cache for ref_a only.
    seed_key = ReviewerCache.cache_key(
        "X 提高 10%", [ref_a], "claim_reviewer|v1",
    )
    cache.put(ReviewerCacheEntry(
        cache_key=seed_key, claim_id="other",
        verdict="contradicted", confidence=0.5, reason="",
        reviewed_at_ms=1,
    ))

    fake = FakeLLMClient()
    fake.script(
        "claim_reviewer",
        '{"verdicts": [{"claim_id": "claim-cache-miss", "verdict": "supported", "confidence": 0.7}]}',
    )
    out = await review_high_risk_claims(
        [claim], source_bytes=b"y" * 1000,
        llm=fake, project_root=None, cache=cache,
    )
    assert out[0].support is ClaimSupport.SUPPORTED
    # LLM was called.
    assert len(fake.calls) == 1
    # Cache now contains the new verdict for ref_b.
    new_key = ReviewerCache.cache_key(claim.text, claim.evidence_refs, "claim_reviewer|v1")
    assert cache.get(new_key) is not None


def test_reviewer_cache_persists_to_jsonl(tmp_path):
    """ReviewerCache.put → .index/reviewer_cache.jsonl 文件存在。"""
    from src.pipeline.v7_extract.claim_reviewer import ReviewerCache, ReviewerCacheEntry

    cache = ReviewerCache(tmp_path)
    cache.put(ReviewerCacheEntry(
        cache_key="rc-test", claim_id="c1",
        verdict="supported", confidence=0.9, reason="ok",
        reviewed_at_ms=1_700_000_000_000,
    ))
    path = tmp_path / ".index" / "reviewer_cache.jsonl"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "rc-test" in text
    assert '"verdict": "supported"' in text
