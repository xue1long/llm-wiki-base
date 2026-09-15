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
