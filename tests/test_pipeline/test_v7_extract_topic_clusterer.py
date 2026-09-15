"""T2.3: Stage 4 topic_clusterer — async LLM + P4 100% coverage."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.topic_clusterer import (
    OTHER_TOPIC_ID,
    OTHER_TOPIC_TITLE,
    Topic,
    _enforce_full_coverage,
    _payload_to_topics,
    _resolve_cluster_template,
    cluster_topics,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient


# ---------------------------------------------------------------------------
# Topic dataclass
# ---------------------------------------------------------------------------

def test_topic_basic():
    t = Topic(id="t1", title="T1", item_ids=["a", "b"])
    assert t.id == "t1"
    assert t.item_ids == ["a", "b"]


# ---------------------------------------------------------------------------
# _payload_to_topics helper
# ---------------------------------------------------------------------------

def test_payload_to_topics_happy_path():
    payload = {
        "topics": [
            {"id": "t1", "title": "Topic 1", "item_ids": ["a", "b"]},
            {"id": "t2", "title": "Topic 2", "item_ids": ["c"]},
        ]
    }
    topics = _payload_to_topics(payload)
    assert len(topics) == 2
    assert topics[0].id == "t1"
    assert topics[0].item_ids == ["a", "b"]
    assert topics[1].title == "Topic 2"


def test_payload_to_topics_skips_non_dict_entries():
    payload = {"topics": ["garbage", {"id": "t1", "title": "T1", "item_ids": []}]}
    topics = _payload_to_topics(payload)
    assert len(topics) == 1
    assert topics[0].id == "t1"


def test_payload_to_topics_renames_duplicate_ids():
    payload = {"topics": [
        {"id": "dup", "title": "A", "item_ids": ["a"]},
        {"id": "dup", "title": "B", "item_ids": ["b"]},
    ]}
    topics = _payload_to_topics(payload)
    assert topics[0].id == "dup"
    assert topics[1].id == "dup-1"


def test_payload_to_topics_handles_missing_topics_key():
    assert _payload_to_topics({}) == []
    assert _payload_to_topics({"topics": None}) == []


def test_payload_to_topics_coerces_item_ids_to_strings():
    payload = {"topics": [{"id": "t1", "title": "T1", "item_ids": [1, 2, "x"]}]}
    topics = _payload_to_topics(payload)
    assert topics[0].item_ids == ["1", "2", "x"]


# ---------------------------------------------------------------------------
# _enforce_full_coverage (P4)
# ---------------------------------------------------------------------------

def _items(*ids: str) -> list[dict]:
    return [{"id": i, "text": f"text-{i}"} for i in ids]


def test_enforce_full_coverage_no_leftover_unchanged():
    topics = [Topic(id="t1", title="T1", item_ids=["a", "b"])]
    out = _enforce_full_coverage(topics, _items("a", "b"))
    assert out == topics


def test_enforce_full_coverage_adds_other_bucket_for_missing():
    topics = [Topic(id="t1", title="T1", item_ids=["a"])]
    items = _items("a", "b", "c")
    out = _enforce_full_coverage(topics, items)

    assert len(out) == 2
    assert out[1].id == OTHER_TOPIC_ID
    assert out[1].title == OTHER_TOPIC_TITLE
    assert set(out[1].item_ids) == {"b", "c"}


def test_enforce_full_coverage_merges_into_existing_other_bucket():
    """If LLM already created __other__, merge leftover into it."""
    topics = [
        Topic(id="t1", title="T1", item_ids=["a"]),
        Topic(id=OTHER_TOPIC_ID, title=OTHER_TOPIC_TITLE, item_ids=["x"]),
    ]
    items = _items("a", "b", "c", "x")
    out = _enforce_full_coverage(topics, items)

    # No duplicate __other__ created; existing one absorbed b, c
    other_topics = [t for t in out if t.id == OTHER_TOPIC_ID]
    assert len(other_topics) == 1
    assert set(other_topics[0].item_ids) == {"b", "c", "x"}


def test_enforce_full_coverage_with_no_llm_topics_at_all():
    """Edge case: LLM produced no topics — all items go to __other__."""
    out = _enforce_full_coverage([], _items("a", "b"))
    assert len(out) == 1
    assert out[0].id == OTHER_TOPIC_ID
    assert set(out[0].item_ids) == {"a", "b"}


# ---------------------------------------------------------------------------
# _resolve_cluster_template helper
# ---------------------------------------------------------------------------

def test_resolve_cluster_template_uses_bundled():
    template = _resolve_cluster_template(project_root=None)
    assert template.prompt_kind == "cluster"
    assert template.source == "bundled"


# ---------------------------------------------------------------------------
# cluster_topics — happy paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cluster_topics_returns_topics():
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": ['
        '{"id": "t1", "title": "Topic 1", "item_ids": ["a", "b"]},'
        '{"id": "t2", "title": "Topic 2", "item_ids": ["c"]}'
        ']}',
    )
    items = _items("a", "b", "c")
    topics = await cluster_topics(items, llm=fake, project_root=None)

    assert len(topics) == 2
    assert topics[0].id == "t1"
    assert topics[0].item_ids == ["a", "b"]
    assert topics[1].id == "t2"
    # No __other__ bucket — every item was assigned
    assert not any(t.id == OTHER_TOPIC_ID for t in topics)


@pytest.mark.asyncio
async def test_cluster_topics_p4_other_bucket_for_missing():
    """P4: if LLM forgets an item, it lands in __other__."""
    fake = FakeLLMClient()
    # LLM only assigns a, b — forgets c
    fake.script("cluster", '{"topics": [{"id": "t1", "title": "T1", "item_ids": ["a", "b"]}]}')

    items = _items("a", "b", "c")
    topics = await cluster_topics(items, llm=fake, project_root=None)

    assert len(topics) == 2
    other = [t for t in topics if t.id == OTHER_TOPIC_ID]
    assert len(other) == 1
    assert other[0].item_ids == ["c"]


# ---------------------------------------------------------------------------
# cluster_topics — failure modes (P2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cluster_topics_returns_other_bucket_on_total_failure():
    """P2: even on total failure, return __other__ bucket with all items."""
    fake = FakeLLMClient()
    fake.script("cluster", "not json")
    fake.script("cluster", "still not json")
    fake.script("cluster", "garbage")

    items = _items("a", "b", "c")
    topics = await cluster_topics(items, llm=fake, project_root=None)

    # All items must survive in __other__ (no silent drop)
    assert len(topics) == 1
    assert topics[0].id == OTHER_TOPIC_ID
    assert set(topics[0].item_ids) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_cluster_topics_handles_llm_raising_exception():
    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    items = _items("a", "b")
    topics = await cluster_topics(items, llm=_ExplodingFake(), project_root=None)

    # P2: never raises; all items in __other__
    assert len(topics) == 1
    assert topics[0].id == OTHER_TOPIC_ID


@pytest.mark.asyncio
async def test_cluster_topics_empty_input_returns_empty():
    fake = FakeLLMClient()
    topics = await cluster_topics([], llm=fake, project_root=None)
    assert topics == []
    # No LLM call when input is empty
    assert len(fake.calls) == 0
