from __future__ import annotations

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    fill_slots,
)
from src.pipeline.v7_extract.topic_clusterer import Topic


def test_fill_slots_returns_all_five_required_concept_slots() -> None:
    page = fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="扩句法通过增加动作、环境和感官细节，让句子更具体。",
    )

    assert isinstance(page, ConceptPage)
    assert tuple(page.slots) == CONCEPT_SLOTS
    assert all(page.slots[name].strip() for name in CONCEPT_SLOTS)
    assert page.type == "concept"
    assert page.sources == ["article-1"]


def test_fill_slots_accepts_scripted_llm_json() -> None:
    llm = FakeLLMClient()
    llm.script(
        "fill_slots",
        '{"slots": {"definition": "精确定义", '
        '"characteristics": "核心特征", "examples": "具体例子", '
        '"related_concepts": "相关概念", "references": "来源文章"}}',
    )

    page = fill_slots(
        {"id": "topic-1", "title": "扩句法", "item_ids": ["article-1"]},
        source_text="来源正文",
        llm=llm,
    )

    assert page.slots["definition"] == "精确定义"
    assert page.slots["references"] == "来源文章"
    assert llm.calls[0]["prompt_kind"] == "fill_slots"


def test_fill_slots_fills_missing_llm_slots_without_extra_keys() -> None:
    llm = FakeLLMClient()
    llm.script("fill_slots", '{"slots": {"definition": "只有定义"}}')

    page = fill_slots(
        Topic("topic-1", "扩句法", ["article-1"]),
        source_text="来源正文",
        llm=llm,
    )

    assert set(page.slots) == set(CONCEPT_SLOTS)
    assert all(page.slots[name].strip() for name in CONCEPT_SLOTS)
    assert "slot:" not in page.body
