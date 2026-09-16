"""Task 15: Stage 5A claim extraction — LLM returns span ids, script maps offsets.

The invariant under test throughout this file: the LLM cites ``span_ids``
and nothing else. Every byte offset on a ``Claim``'s ``EvidenceRef`` is
mapped by the script from the ``CanonicalSpan`` it resolved that id to, so
a hallucinated id can only ever cost evidence (never invent it).
"""
from __future__ import annotations

import json

import pytest

from src.pipeline.v7_extract.canonical_spans import build_canonical_spans
from src.pipeline.v7_extract.claim import ClaimRisk, ClaimSupport
from src.pipeline.v7_extract.claim_extractor import (
    MAX_CLAIMS_PER_SLOT,
    SlotExtraction,
    extract_slot_claims,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.segmentation import CanonicalItem, ItemKind

PROMPT_KIND = "fill_slots_extract"


class _CapturingLLM(FakeLLMClient):
    """FakeLLMClient that also keeps the rendered prompts it was called with.

    ``FakeLLMClient`` only logs prompt *lengths*, and one of the Stage 5A
    invariants is about prompt *content* (no offset instructions), so the
    test needs the raw text.
    """

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


def _build(texts: list[str], *, prefix_bytes: int = 0):
    """Source bytes + canonical spans (one span per text, all short).

    ``prefix_bytes`` shifts the item's source-absolute base so a test can
    prove the mapped offsets are NOT item-local char indexes.
    """
    items: list[CanonicalItem] = []
    offset = prefix_bytes
    for index, text in enumerate(texts, start=1):
        body = text.encode("utf-8")
        items.append(
            CanonicalItem(
                item_id=f"item-{index}",
                kind=ItemKind.ARTICLE,
                start_byte=offset,
                end_byte=offset + len(body),
                title=None,
                text=text,
            )
        )
        offset += len(body)

    source_bytes = b"x" * prefix_bytes + b"".join(t.encode("utf-8") for t in texts)
    spans = build_canonical_spans(items)
    assert len(spans) == len(texts)  # one span per item — keeps ids predictable
    return source_bytes, spans


def _script(llm: FakeLLMClient, claims: list[dict]) -> None:
    llm.script(PROMPT_KIND, json.dumps({"claims": claims}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_extract_slot_claims_returns_evidence_backed_claims() -> None:
    source_bytes, spans = _build([
        "扩句法是一种让句子更具体的写作方法。",
        "扩句法的核心是补充名词的修饰成分。",
    ])
    llm = FakeLLMClient()
    _script(llm, [
        {
            "text": "扩句法是一种让句子更具体的写作方法。",
            "span_ids": [spans[0].span_id, spans[1].span_id],
            "confidence": 0.8,
        },
        {
            "text": "扩句法的核心是补充名词的修饰成分。",
            "span_ids": [spans[1].span_id],
            "confidence": 0.6,
        },
    ])

    result = await extract_slot_claims(
        "definition",
        topic_label="扩句法",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert isinstance(result, SlotExtraction)
    assert result.slot_name == "definition"
    assert result.status is ClaimSupport.SUPPORTED
    assert [c.text for c in result.claims] == [
        "扩句法是一种让句子更具体的写作方法。",
        "扩句法的核心是补充名词的修饰成分。",
    ]

    first = result.claims[0]
    assert first.support is ClaimSupport.SUPPORTED
    assert first.confidence == pytest.approx(0.8)
    assert first.risk is ClaimRisk.LOW
    assert len(first.evidence_refs) == 2

    ref = first.evidence_refs[0]
    assert ref.item_id == spans[0].item_id == "item-1"
    assert ref.item_index == spans[0].item_index == 0
    assert ref.span_index == 0
    assert ref.start_byte == spans[0].start_byte
    assert ref.end_byte == spans[0].end_byte
    assert ref.excerpt_from(source_bytes) == "扩句法是一种让句子更具体的写作方法。"

    second_ref = result.claims[1].evidence_refs[0]
    assert second_ref.span_index == 1
    assert second_ref.item_id == "item-2"
    assert llm.calls[0]["prompt_kind"] == PROMPT_KIND


@pytest.mark.asyncio
async def test_llm_returns_span_indexes_not_byte_offsets() -> None:
    prefix = 37
    source_bytes, spans = _build(
        ["证据链必须能回溯到原始字节。"], prefix_bytes=prefix
    )
    llm = _CapturingLLM()
    _script(llm, [{
        "text": "证据链必须能回溯到原始字节。",
        "span_ids": [spans[0].span_id],
        "confidence": 0.9,
    }])

    result = await extract_slot_claims(
        "definition",
        topic_label="证据链",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    system_prompt, user_prompt = llm.prompts[0]
    # the user message asks for span ids and never for byte positions
    assert spans[0].span_id in user_prompt
    assert "span_ids" in user_prompt
    for forbidden in ("start_byte", "end_byte", "char_start", "char_end", "offset"):
        assert forbidden not in user_prompt.lower()
    # ... and the system message forbids offsets outright
    assert "NEVER invent a span id" in system_prompt
    assert "NEVER output byte offsets" in system_prompt

    # the offsets on the emitted ref were mapped by the script, not returned
    # by the LLM: they are source-absolute and shifted by the item's byte base
    ref = result.claims[0].evidence_refs[0]
    assert ref.start_byte == spans[0].start_byte == prefix
    assert ref.end_byte == spans[0].end_byte
    assert ref.start_byte != spans[0].char_start  # 37 bytes vs 0 chars


@pytest.mark.asyncio
async def test_unknown_span_ids_are_dropped_not_raised() -> None:
    source_bytes, spans = _build(["只有这一条候选证据。"])
    llm = FakeLLMClient()
    _script(llm, [
        {
            "text": "这条论断引用了一个不存在的 span。",
            "span_ids": ["span-deadbeef0000"],
            "confidence": 0.9,
        },
        {
            "text": "这条论断引用了真实与伪造的混合 span。",
            "span_ids": ["span-deadbeef0000", spans[0].span_id],
            "confidence": 0.7,
        },
    ])

    result = await extract_slot_claims(
        "definition",
        topic_label="证据链",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert len(result.claims) == 2

    fabricated = result.claims[0]
    assert fabricated.evidence_refs == []
    assert fabricated.support is ClaimSupport.INSUFFICIENT_EVIDENCE

    mixed = result.claims[1]
    assert [r.span_index for r in mixed.evidence_refs] == [0]
    assert mixed.support is ClaimSupport.SUPPORTED

    # one supported claim is enough to keep the slot out of the
    # all-insufficient rollup
    assert result.status is ClaimSupport.SUPPORTED


@pytest.mark.asyncio
async def test_high_risk_claims_detected_by_regex() -> None:
    texts = [
        "准确率提高 10%",
        "不适用于小数据集",
        "导致收敛变慢",
    ]
    source_bytes, spans = _build(["高风险论断来自这里的候选证据。"])
    llm = FakeLLMClient()
    _script(llm, [
        {"text": t, "span_ids": [spans[0].span_id], "confidence": 0.8}
        for t in texts
    ])

    result = await extract_slot_claims(
        "characteristics",
        topic_label="检索增强生成",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert [c.text for c in result.claims] == texts
    assert all(c.risk is ClaimRisk.HIGH for c in result.claims)


@pytest.mark.asyncio
async def test_plain_descriptive_claim_is_low_risk() -> None:
    """Discrimination guard: the bare copulas 是/为 are intentionally NOT
    high-risk — flagging them would mark nearly every definitional
    sentence and make the Task 17 reviewer economically useless."""
    source_bytes, spans = _build(["RAG 是一种检索增强生成方法。"])
    llm = FakeLLMClient()
    _script(llm, [{
        "text": "RAG 是一种检索增强生成方法",
        "span_ids": [spans[0].span_id],
        "confidence": 0.9,
    }])

    result = await extract_slot_claims(
        "definition",
        topic_label="RAG",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert len(result.claims) == 1
    assert result.claims[0].risk is ClaimRisk.LOW
    assert result.status is ClaimSupport.SUPPORTED


@pytest.mark.asyncio
async def test_claim_id_is_script_generated_and_deterministic() -> None:
    text = "论断标识必须由脚本生成而不是模型生成。"
    source_bytes, spans = _build(["论断标识必须由脚本生成而不是模型生成。"])
    payload = [{"text": text, "span_ids": [spans[0].span_id], "confidence": 0.5}]

    def _client() -> FakeLLMClient:
        llm = FakeLLMClient()
        _script(llm, payload)
        return llm

    first = await extract_slot_claims(
        "definition", topic_label="标识", spans=spans, llm=_client(),
        source_bytes=source_bytes,
    )
    second = await extract_slot_claims(
        "definition", topic_label="标识", spans=spans, llm=_client(),
        source_bytes=source_bytes,
    )

    claim_id = first.claims[0].claim_id
    assert claim_id == second.claims[0].claim_id
    assert claim_id.startswith("claim-")
    assert len(claim_id) == len("claim-") + 12
    # the LLM's own text is an INPUT to the digest, never a component of the id
    assert text not in claim_id
    assert spans[0].span_id not in claim_id


@pytest.mark.asyncio
async def test_claims_capped_at_max_claims_per_slot() -> None:
    source_bytes, spans = _build(["候选证据一。", "候选证据二。"])
    llm = FakeLLMClient()
    _script(llm, [
        {
            "text": f"第 {index} 条论断有证据支持。",
            "span_ids": [spans[index % len(spans)].span_id],
            "confidence": 0.5,
        }
        for index in range(10)
    ])

    result = await extract_slot_claims(
        "characteristics",
        topic_label="容量上限",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert MAX_CLAIMS_PER_SLOT == 6
    assert len(result.claims) == 6
    assert [c.text for c in result.claims] == [
        f"第 {index} 条论断有证据支持。" for index in range(6)
    ]


@pytest.mark.asyncio
async def test_duplicate_claim_text_deduped() -> None:
    text = "重复出现的论断只保留第一条。"
    source_bytes, spans = _build(["重复出现的论断只保留第一条。"])
    llm = FakeLLMClient()
    _script(llm, [
        {"text": text, "span_ids": [spans[0].span_id], "confidence": 0.9},
        {"text": text, "span_ids": [spans[0].span_id], "confidence": 0.4},
    ])

    result = await extract_slot_claims(
        "definition",
        topic_label="去重",
        spans=spans,
        llm=llm,
        source_bytes=source_bytes,
    )

    assert len(result.claims) == 1
    assert result.claims[0].text == text
    assert result.claims[0].confidence == pytest.approx(0.9)  # first wins
