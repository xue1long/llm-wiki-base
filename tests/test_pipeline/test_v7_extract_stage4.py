from __future__ import annotations

from src.pipeline.v7_extract.concept_deduplicator import (
    ConceptCandidate,
    deduplicate_concepts,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.topic_clusterer import Topic, cluster_topics


def _bridge_items(count: int = 103) -> list[dict[str, str]]:
    labels = ("冲突升级", "角色动机", "世界观设定", "节奏转折")
    return [
        {"id": f"bridge-{i}", "text": f"{labels[i % len(labels)]}：桥段 {i}"}
        for i in range(count)
    ]


def test_103_bridge_items_are_bounded_to_three_to_five_topics() -> None:
    topics = cluster_topics(_bridge_items())

    assert 3 <= len(topics) <= 5
    assert sum(len(topic.item_ids) for topic in topics) == 103
    assert {item_id for topic in topics for item_id in topic.item_ids} == {
        f"bridge-{i}" for i in range(103)
    }


def test_cluster_topics_uses_llm_topics_and_assignments() -> None:
    llm = FakeLLMClient()
    llm.script(
        "cluster",
        '{"topics": [{"id": "conflict", "title": "冲突升级", '
        '"item_ids": ["a", "b"]}, {"id": "motivation", "title": "角色动机", '
        '"item_ids": ["c"]}]}',
    )

    topics = cluster_topics(
        [
            {"id": "a", "text": "对手正面冲突"},
            {"id": "b", "text": "冲突升级"},
            {"id": "c", "text": "主角的选择动机"},
        ],
        llm=llm,
    )

    assert topics == [
        Topic(id="conflict", title="冲突升级", item_ids=["a", "b"]),
        Topic(id="motivation", title="角色动机", item_ids=["c"]),
    ]
    assert llm.calls[0]["prompt_kind"] == "cluster"


def test_concept_deduplicator_merges_existing_concept_sources() -> None:
    concepts = [
        ConceptCandidate(
            id="kuo-ju-fa",
            title="扩句法",
            source_ids=["new-article"],
            body="把短句扩写成有画面的句子。",
        ),
    ]

    result = deduplicate_concepts(
        concepts,
        existing_concepts=[
            {
                "id": "kuo-ju-fa",
                "title": "扩句法",
                "source_ids": ["old-article"],
            },
        ],
    )

    assert result == [
        ConceptCandidate(
            id="kuo-ju-fa",
            title="扩句法",
            source_ids=["old-article", "new-article"],
            body="把短句扩写成有画面的句子。",
        ),
    ]


def test_concept_deduplicator_is_idempotent_and_suffixes_new_same_title() -> None:
    concepts = [
        ConceptCandidate("new", "冲突升级", ["source-1"], "body"),
        ConceptCandidate("new", "冲突升级", ["source-1"], "body"),
    ]

    first = deduplicate_concepts(concepts)
    second = deduplicate_concepts(first)

    assert first == second
    assert [concept.id for concept in first] == ["new", "new-2"]
    assert first[1].source_ids == ["source-1"]
