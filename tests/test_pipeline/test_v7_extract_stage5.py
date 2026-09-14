from __future__ import annotations

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    fill_slots,
)
from src.pipeline.v7_extract.topic_clusterer import Topic


def test_fill_slots_returns_all_five_required_concept_slots() -> None:
    """Even without an LLM, the page still exposes all five required slot
    names. Empty slots are flagged needs_review rather than filled with
    forbidden placeholder strings."""
    page = fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="扩句法通过增加动作、环境和感官细节，让句子更具体。",
    )

    assert isinstance(page, ConceptPage)
    assert tuple(page.slots) == CONCEPT_SLOTS
    assert page.type == "concept"
    assert page.sources == ["article-1"]
    # No LLM -> no evidence -> every slot is flagged for review, no body
    # sneaks in a forbidden placeholder.
    assert set(page.needs_review_slots) == set(CONCEPT_SLOTS)
    assert page.has_evidence is False
    for body in page.slots.values():
        assert body == "" or "需结合原文核对" not in body
        assert body == "" or "来源未提供" not in body


def test_fill_slots_accepts_scripted_llm_json_with_evidence() -> None:
    """LLM response with both slots and evidence is accepted verbatim."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "精确定义", '
        '"characteristics": "核心特征", "examples": "具体例子", '
        '"related_concepts": "相关概念", "references": "来源文章"}, '
        '"evidence": {"definition": {"item_id": "article-1", '
        '"source_text_excerpt": "扩句法原文摘录"}, '
        '"characteristics": {"item_id": "article-1", '
        '"source_text_excerpt": "核心特征原文"}, '
        '"examples": {"item_id": "article-1", '
        '"source_text_excerpt": "具体例子原文"}, '
        '"related_concepts": {"item_id": "article-1", '
        '"source_text_excerpt": "相关概念原文"}, '
        '"references": {"item_id": "article-1", '
        '"source_text_excerpt": "来源文章原文"}}}',
    )

    page = fill_slots(
        {"id": "topic-1", "title": "扩句法", "item_ids": ["article-1"]},
        source_text=(
            "扩句法原文摘录 扩句法让句子更具体。 核心特征原文 具体例子原文 "
            "相关概念原文 来源文章原文"
        ),
        llm=llm,
        item_texts={"article-1": "扩句法通过增加动作、环境和感官细节，让句子更具体。"},
    )

    assert page.slots["definition"] == "精确定义"
    assert page.slots["references"] == "来源文章"
    assert llm.calls[0]["prompt_kind"] == "fill_slots"
    # All five slots cite the known article-1 item -> no needs_review.
    assert page.needs_review_slots == ()


def test_fill_slots_fills_missing_llm_slots_without_extra_keys() -> None:
    """LLM only provides definition — other slots stay empty/flagged, no
    placeholder text sneaks in via the body."""
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "只有定义"}, '
        '"evidence": {"definition": {"item_id": "article-1", '
        '"source_text_excerpt": "只有定义"}}}',
    )

    page = fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="扩句法只有定义",
        llm=llm,
        item_texts={"article-1": "扩句法只有定义的内容。"},
    )

    assert set(page.slots) == set(CONCEPT_SLOTS)
    # Only the supplied slot carries evidence; the others are flagged.
    assert "definition" not in page.needs_review_slots
    assert set(page.needs_review_slots) <= set(CONCEPT_SLOTS) - {"definition"}
    assert "slot:" not in page.body


def test_fill_slots_flags_forbidden_placeholder_as_needs_review() -> None:
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
        '"evidence": {"characteristics": {"item_id": "article-1", '
        '"source_text_excerpt": "真实特征"}, '
        '"related_concepts": {"item_id": "article-1", '
        '"source_text_excerpt": "相关概念"}, '
        '"references": {"item_id": "article-1", '
        '"source_text_excerpt": "来源文章"}}}',
    )

    page = fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="真实特征 真实文本 真实特征 相关概念 真实来源文章",
        llm=llm,
        item_texts={"article-1": "真实特征 内容"},
    )

    assert "definition" in page.needs_review_slots
    assert "examples" in page.needs_review_slots
    # The other slots are evidence-backed.
    assert "characteristics" not in page.needs_review_slots
    assert page.has_evidence is False
