from __future__ import annotations

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.relation_extractor import (
    PageRelation,
    extract_relations,
)
from src.pipeline.v7_extract.slot_filler import ConceptPage, CONCEPT_SLOTS


def _page(page_id: str, title: str, *, related: str = "", characteristics: str = "") -> ConceptPage:
    slots = {name: "来源内容" for name in CONCEPT_SLOTS}
    slots["related_concepts"] = related
    slots["characteristics"] = characteristics or "核心特征"
    return ConceptPage(page_id, title, slots, [f"source-{page_id}"])


def test_extract_relations_distinguishes_refines_and_supported_by() -> None:
    pages = [
        _page("base", "扩句法"),
        _page(
            "advanced",
            "场景扩句法",
            related="扩句法",
            characteristics="在扩句法基础上针对场景细化。",
        ),
        _page("evidence", "扩句法案例", related="扩句法"),
    ]

    relations = extract_relations(pages)

    assert PageRelation("advanced", "base", "refines") in relations
    assert PageRelation("evidence", "base", "supported_by") in relations


def test_extract_relations_accepts_llm_edges_and_deduplicates_them() -> None:
    llm = FakeLLMClient()
    llm.script(
        "extract_relations",
        '''{"relations": [
          {"source_id":"child","target_id":"parent","type":"refines"},
          {"source_id":"child","target_id":"parent","type":"refines"}
        ]}''',
    )
    pages = [_page("parent", "基础概念"), _page("child", "进阶概念")]

    relations = extract_relations(pages, llm=llm)

    assert relations == [PageRelation("child", "parent", "refines")]
    assert llm.calls[0]["prompt_kind"] == "extract_relations"


def test_extract_relations_ignores_self_loops_and_unknown_targets() -> None:
    llm = FakeLLMClient()
    llm.script(
        "extract_relations",
        '''{"relations": [
          {"source_id":"same","target_id":"same","type":"refines"},
          {"source_id":"same","target_id":"missing","type":"refines"},
          {"source_id":"same","target_id":"other","type":"unsupported"}
        ]}''',
    )
    pages = [_page("same", "概念一"), _page("other", "概念二")]

    assert extract_relations(pages, llm=llm) == []
