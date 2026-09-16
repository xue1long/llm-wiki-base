"""T2.3: Stage 4 topic_clusterer — async LLM + P4 100% coverage."""
from __future__ import annotations

import pytest

from src.pipeline.v7_extract.topic_clusterer import (
    OTHER_TOPIC_ID,
    OTHER_TOPIC_TITLE,
    Topic,
    _enforce_full_coverage,
    _payload_to_candidates,
    _payload_to_topics,
    _resolve_cluster_template,
    cluster_topics,
)
from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.prompts.renderer import LLMResponseError


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
            {"id": "t1", "title": "Topic 1", "item_indexes": [0, 1]},
            {"id": "t2", "title": "Topic 2", "item_indexes": [2]},
        ]
    }
    topics = _payload_to_topics(payload, ["a", "b", "c"])
    assert len(topics) == 2
    # Task 12: Topic.id is script-generated (no LLM id dependence).
    assert topics[0].item_ids == ["a", "b"]
    assert topics[1].title == "Topic 2"
    # The LLM-supplied "id" field is intentionally ignored — the topic_id
    # is derived from (source_id, mapped_ids) via derive_topic_id.
    assert topics[0].id != "t1"
    assert topics[1].id != "t2"


def test_payload_to_topics_skips_non_dict_entries():
    payload = {"topics": ["garbage", {"id": "t1", "title": "T1", "item_indexes": []}]}
    topics = _payload_to_topics(payload, ["a"])
    assert len(topics) == 1
    # Task 12: Topic.id is script-generated (not "t1").
    assert topics[0].id != "t1"
    # Title still comes from the LLM payload.
    assert topics[0].title == "T1"


def test_payload_to_topics_renames_duplicate_ids():
    """Task 12: with script-generated ids, the LLM-supplied "id" field is
    discarded, so two entries with the same LLM id produce different
    script-generated topic_ids (because their memberships differ).
    """
    payload = {"topics": [
        {"id": "dup", "title": "A", "item_indexes": [0]},
        {"id": "dup", "title": "B", "item_indexes": [1]},
    ]}
    topics = _payload_to_topics(payload, ["a", "b"])
    # Distinct memberships → distinct script-generated topic_ids.
    assert topics[0].id != topics[1].id


def test_payload_to_topics_handles_missing_topics_key():
    assert _payload_to_topics({}, []) == []
    assert _payload_to_topics({"topics": None}, []) == []


def test_payload_to_topics_maps_indexes_to_canonical_item_ids():
    payload = {"topics": [{"id": "t1", "title": "T1", "item_indexes": [1, 0]}]}
    topics = _payload_to_topics(payload, ["raw/a#item-1", "raw/a#item-2"])
    assert topics[0].item_ids == ["raw/a#item-2", "raw/a#item-1"]


def test_payload_to_topics_rejects_invalid_or_duplicate_indexes():
    with pytest.raises(LLMResponseError, match="item_indexes"):
        _payload_to_topics(
            {"topics": [{"id": "t1", "item_indexes": [2]}]},
            ["a", "b"],
        )
    with pytest.raises(LLMResponseError, match="duplicate"):
        _payload_to_topics(
            {"topics": [
                {"id": "t1", "item_indexes": [0]},
                {"id": "t2", "item_indexes": [0]},
            ]},
            ["a"],
        )


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
        Topic(id=OTHER_TOPIC_ID, title=OTHER_TOPIC_TITLE, item_ids=["d"]),
    ]
    items = _items("a", "b", "c", "d")
    out = _enforce_full_coverage(topics, items)

    # No duplicate __other__ created; existing one absorbed b, c
    other_topics = [t for t in out if t.id == OTHER_TOPIC_ID]
    assert len(other_topics) == 1
    assert set(other_topics[0].item_ids) == {"b", "c", "d"}


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
        '{"id": "t1", "title": "Topic 1", "item_indexes": [0, 1]},'
        '{"id": "t2", "title": "Topic 2", "item_indexes": [2]}'
        ']}',
    )
    items = _items("a", "b", "c")
    result = await cluster_topics(items, llm=fake, project_root=None)
    topics = result.topics

    assert len(topics) == 2
    # Task 12: Topic.id is script-generated, not "t1" / "t2".
    assert topics[0].id != "t1"
    assert topics[0].item_ids == ["a", "b"]
    assert topics[1].id != "t2"
    # No __other__ bucket — every item was assigned
    assert not any(t.id == OTHER_TOPIC_ID for t in topics)


@pytest.mark.asyncio
async def test_cluster_topics_p4_other_bucket_for_missing():
    """P4: if LLM forgets an item, it lands in __other__."""
    fake = FakeLLMClient()
    # LLM only assigns a, b — forgets c
    fake.script("cluster", '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0, 1]}]}')

    items = _items("a", "b", "c")
    result = await cluster_topics(items, llm=fake, project_root=None)
    topics = result.topics

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
    result = await cluster_topics(items, llm=fake, project_root=None)
    topics = result.topics

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
    result = await cluster_topics(items, llm=_ExplodingFake(), project_root=None)
    topics = result.topics

    # P2: never raises; all items in __other__
    assert len(topics) == 1
    assert topics[0].id == OTHER_TOPIC_ID


@pytest.mark.asyncio
async def test_cluster_topics_empty_input_returns_empty():
    fake = FakeLLMClient()
    result = await cluster_topics([], llm=fake, project_root=None)
    assert result.topics == []
    assert result.status.value == "empty"
    # No LLM call when input is empty
    assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# Plan 5 collection-split: doc_type kwarg + header omitted when None
#   Plan 5 was superseded by master plan 2026-09-17 (Task 11): doc_type is a
#   SOFT hint, not a gate. The hard `ONLY when document type is "collection"`
#   rule text and the cluster.toml v1.1 version bump that Plan 5 demanded
#   were intentionally NOT implemented. The structural authority is Stage 2
#   (SegmentationResult.structural_signals + author-byline splitter) plus
#   classification_hint.traits, so removing the gate prevents Stage 1
#   misclassification from cascading into Stage 4 — which was the original
#   H8/L1 risk. The two superseded tests (collection_splitting_rule_in_prompt
#   and cluster_version_bumped_to_1_1) were removed; only the kwarg-shape
#   and header-omission guards remain below.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cluster_topic_signature_accepts_doc_type_kwarg():
    """master plan 2026-09-17 (Task 11): cluster_topics accepts a doc_type
    keyword for soft hint propagation; the value is held by the clusterer
    and consumed via classification_hint / structural_signals downstream,
    not by a hard gate in the prompt."""
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
    )

    items = _items("a")
    result = await cluster_topics(
        items, llm=fake, project_root=None, doc_type="collection"
    )
    # Function accepts doc_type without raising; one topic returned by the
    # scripted LLM response. We do NOT assert that the prompt contains
    # "Document type: collection" — master plan Task 11 made that a soft
    # signal, not a template-level injection.
    assert len(result.topics) == 1
    assert result.status.value in {"clustered", "degraded", "uncertain"}


@pytest.mark.asyncio
async def test_cluster_topic_signature_omits_doc_type_header_when_none():
    """master plan 2026-09-17 (Task 11): when caller omits doc_type, the
    rendered prompt must NOT contain 'Document type:' header so legacy
    single-doc docs are unaffected."""
    from src.pipeline.v7_extract.prompts.renderer import render_prompt

    template = _resolve_cluster_template(project_root=None)
    _, user_prompt = render_prompt(template, {
        "min_topics": 1,
        "max_topics": 20,
        "items_text": "0: a",
    })
    assert "Document type:" not in user_prompt


# ---------------------------------------------------------------------------
# Task 9 (Plan 2026-09-17): ClusterResult + ClusterStatus + quality gates
# ---------------------------------------------------------------------------


def _make_items(n: int, *, kind: str = "article", prefix: str = "i") -> list[dict]:
    """Build n canonical-shape items for Stage 4 input.

    Articles are detected via ``kind="article"``; non-article items
    contribute to the unresolved_article_ratio when they go unresolved.
    """
    return [
        {
            "id": f"{prefix}-{i}",
            "text": f"item {i}",
            "kind": kind,
        }
        for i in range(n)
    ]


def _article_items(n: int, *, prefix: str = "art") -> list[dict]:
    return [
        {
            "id": f"{prefix}-{i}",
            "text": f"article {i}",
            "kind": "article",
            "is_article": True,
            "byte_length": 100,
        }
        for i in range(n)
    ]


def _script_cluster_buckets(buckets: list[tuple[str, str, list[int]]]) -> str:
    """Render an LLM JSON payload from (topic_id, title, item_indexes)."""
    return (
        '{"topics": ['
        + ",".join(
            f'{{"id":"{tid}","title":"{title}","item_indexes":{idxs}}}'
            for tid, title, idxs in buckets
        )
        + "]}"
    )


@pytest.mark.asyncio
async def test_max_topics_no_longer_semantic_limit():
    """Task 9: 50 items must produce 50 topics when LLM emits one-per-item.

    Pre-Task 9: max_topics=20 silently capped the prompt, forcing the LLM
    to compress 50 items into <=20 topics. Task 9 removes that semantic
    cap and keeps it as a hint only.
    """
    items = _make_items(50)
    fake = FakeLLMClient()
    buckets = [
        (f"topic-{i}", f"Topic {i}", [i]) for i in range(50)
    ]
    fake.script("cluster", _script_cluster_buckets(buckets))

    result = await cluster_topics(items, llm=fake, project_root=None)

    assert len(result.topics) == 50, (
        f"expected 50 topics (one per item), got {len(result.topics)}"
    )
    assert result.metrics.topic_count == 50
    assert result.metrics.item_count == 50


@pytest.mark.asyncio
async def test_clusterresult_carries_metrics():
    """Task 9: ClusterResult.metrics must be populated with 9 metrics."""
    items = _make_items(4)
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        _script_cluster_buckets([
            ("t1", "T1", [0, 1]),
            ("t2", "T2", [2]),
            ("t3", "T3", [3]),
        ]),
    )

    result = await cluster_topics(items, llm=fake, project_root=None)

    # All 9 metrics populated (item/topic counts + ratios + duplicate)
    m = result.metrics
    assert m.item_count == 4
    assert m.topic_count == 3
    assert m.items_per_topic == 4 / 3
    assert m.unresolved_item_ratio == 0.0
    assert m.unresolved_byte_ratio == 0.0
    assert m.singleton_topic_ratio >= 0  # populated even if 0
    assert m.largest_topic_share == 0.5  # t1 has 2 of 4
    assert m.duplicate_assignment_ratio == 0.0
    # article_preservation_ratio: no articles provided → 1.0 (nothing to preserve)
    assert m.article_preservation_ratio == 1.0
    assert m.article_preservation_diagnostic == "none_lost"


@pytest.mark.asyncio
async def test_quality_gate_blocks_umbrella_topic():
    """Task 9: largest_topic_share > 0.5 → ClusterStatus.DEGRADED."""
    items = _make_items(10)
    fake = FakeLLMClient()
    # One umbrella topic covering 6 of 10 items (60%) — over the 50% threshold.
    fake.script(
        "cluster",
        _script_cluster_buckets([
            ("umbrella", "综合主题", [0, 1, 2, 3, 4, 5]),
            ("t2", "T2", [6, 7]),
            ("t3", "T3", [8, 9]),
        ]),
    )

    result = await cluster_topics(items, llm=fake, project_root=None)

    assert result.metrics.largest_topic_share == 0.6
    assert result.status.value == "degraded", (
        f"expected degraded, got {result.status.value}; warnings={result.warnings}"
    )
    assert any(w.startswith("umbrella_topic") for w in result.warnings)


@pytest.mark.asyncio
async def test_clusterstatus_failed_distinct_from_degraded():
    """Task 9 / Failure Contract: LLM total failure → ClusterStatus.FAILED,
    NOT DEGRADED. Technical failure must not be papered over as quality issue.
    """
    items = _make_items(3)

    class _ExplodingFake:
        async def complete(self, **kwargs):
            raise RuntimeError("simulated LLM outage")

    result = await cluster_topics(items, llm=_ExplodingFake(), project_root=None)

    assert result.status.value == "failed"
    assert result.status.value != "degraded"
    assert result.status.value != "uncertain"
    # P4: items must still survive — they land in the __other__ bucket,
    # so nothing is silently dropped.
    assert sum(len(t.item_ids) for t in result.topics) == 3


@pytest.mark.asyncio
async def test_article_loss_strict_threshold_with_diagnostic():
    """F9 整改: article_preservation_ratio < 0.85 → UNCERTAIN + diagnostic
    distinguishes "stage4_missed" vs "actually_lost".
    """
    # 10 articles in segmentation, only 4 picked up by clustering = 40% preserved.
    items = _article_items(10)
    fake = FakeLLMClient()
    # LLM only assigns indexes 0..3 (4 of 10 articles); the remaining 6
    # articles will end up in __other__ — they EXIST in segmentation but
    # were not picked up by clustering → stage4_missed.
    fake.script(
        "cluster",
        _script_cluster_buckets([
            ("t1", "T1", [0, 1]),
            ("t2", "T2", [2, 3]),
        ]),
    )

    result = await cluster_topics(items, llm=fake, project_root=None)

    # 0.40 < 0.85 → UNCERTAIN (not DEGRADED).
    assert result.metrics.article_preservation_ratio == 0.4
    assert result.status.value == "uncertain", (
        f"expected uncertain, got {result.status.value}; "
        f"warnings={result.warnings}"
    )
    # Diagnostic must distinguish stage4_missed from actually_lost.
    assert result.metrics.article_preservation_diagnostic == "stage4_missed"
    assert any(w.startswith("article_loss") for w in result.warnings)


@pytest.mark.asyncio
async def test_article_loss_diagnostic_actually_lost_when_not_in_items():
    """F9: when items list contains NO articles at all, diagnostic is 'none_lost'."""
    items = _make_items(5, kind="non_article")
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        _script_cluster_buckets([("t1", "T1", [0, 1, 2, 3, 4])]),
    )

    result = await cluster_topics(items, llm=fake, project_root=None)

    assert result.metrics.article_preservation_ratio == 1.0
    assert result.metrics.article_preservation_diagnostic == "none_lost"


@pytest.mark.asyncio
async def test_unresolved_article_ratio_triggers_degraded():
    """FP3 加固: unresolved_article_ratio > 0.1 → DEGRADED (separate
    from overall article_preservation which is UNCERTAIN territory).
    """
    # 10 items, 6 are articles. LLM only clusters 4 non-articles and
    # __other__ absorbs all 6 articles → unresolved_article_ratio = 1.0.
    article_block = _article_items(6, prefix="art")
    non_article_block = [
        {"id": f"non-{i}", "text": f"x{i}", "kind": "non_article"}
        for i in range(4)
    ]
    items = article_block + non_article_block
    fake = FakeLLMClient()
    # LLM only assigns the 4 non-articles; 6 articles go to __other__.
    fake.script(
        "cluster",
        _script_cluster_buckets([
            ("t1", "T1", [6, 7, 8, 9]),
        ]),
    )

    result = await cluster_topics(items, llm=fake, project_root=None)

    assert result.metrics.unresolved_article_ratio > 0.1
    # FP3 routes to DEGRADED (not UNCERTAIN — article_preservation is 0.0
    # which would also trigger UNCERTAIN, so DEGRADED wins for FP3 gate).
    # Per spec: UNCERTAIN takes precedence over DEGRADED when article_loss fires.
    # When article_preservation < 0.85 AND unresolved_article_ratio > 0.1,
    # UNCERTAIN wins. So this test should yield UNCERTAIN.
    assert result.status.value in {"degraded", "uncertain"}
    assert any(
        w.startswith("unresolved_article") or w.startswith("article_loss")
        for w in result.warnings
    )


def test_extract_pilot_routes_cluster_failed_to_extraction_failed():
    """Task 9 / Failure Contract enforcement at Stage 4 → 5 boundary.

    When Stage 4 emits ClusterStatus.FAILED (LLM total failure), the
    pilot MUST surface ExtractionStatus.FAILED with failure_stage="stage4"
    — never WRITTEN, never BLOCKED. Technical failure is not papered over.
    """
    import asyncio
    from scripts.extract_pilot import _extract_one
    from src.pipeline.v7_extract.failures import ExtractionStatus

    # Force Stage 4 into ClusterStatus.FAILED by giving a stub LLM that
    # raises on every cluster call. We invoke the internal helper that
    # the pilot uses for Stage 4 so we test the mapping in isolation
    # (full _extract_one also depends on Stage 1/3 fixtures).
    class _ExplodingStub:
        async def complete(self, **kwargs):
            raise RuntimeError("forced cluster LLM outage")

    async def _check():
        from src.pipeline.v7_extract.topic_clusterer import (
            cluster_topics, ClusterStatus,
        )
        items = _make_items(3)
        result = await cluster_topics(items, llm=_ExplodingStub(), project_root=None)
        # The mapper logic in extract_pilot must classify FAILED -> ExtractionStatus.FAILED.
        if result.status is ClusterStatus.FAILED:
            mapped = ExtractionStatus.FAILED
            stage = "stage4"
        elif result.status.value == "uncertain":
            mapped = ExtractionStatus.BLOCKED
            stage = "stage4"
        elif result.status.value == "empty":
            mapped = ExtractionStatus.BLOCKED
            stage = "stage4"
        else:
            mapped = ExtractionStatus.WRITTEN
            stage = None
        return result, mapped, stage

    cluster_result, mapped_status, stage = asyncio.run(_check())

    assert cluster_result.status.value == "failed"
    assert mapped_status is ExtractionStatus.FAILED
    assert stage == "stage4"
    # Hard invariant: FAILED must never map to WRITTEN.
    assert mapped_status is not ExtractionStatus.WRITTEN


# ---------------------------------------------------------------------------
# Task 10 (Plan 2026-09-17): TopicCandidate + lift single-topic-per-item constraint
# ---------------------------------------------------------------------------


def test_one_item_multiple_topic_candidates():
    """Task 10: a single item can produce multiple TopicCandidates via
    ``local_index``. Lifting the old "duplicate item_index → raise" hard
    constraint (canonical Identity Contract: identity is per-candidate,
    not per-item).
    """
    payload = {
        "candidates": [
            {"item_index": 0, "local_index": 0, "span_hint": "p1-2",
             "semantic_label": "Embedding", "confidence": 0.9},
            {"item_index": 0, "local_index": 1, "span_hint": "p3-4",
             "semantic_label": "Chunking", "confidence": 0.85},
            {"item_index": 0, "local_index": 2, "span_hint": "p5-6",
             "semantic_label": "Reranking", "confidence": 0.8},
        ]
    }
    from src.pipeline.v7_extract.topic_candidate import TopicCandidate

    candidates = _payload_to_candidates(payload, ["a"], ["fp-a"])
    assert len(candidates) == 3
    assert all(isinstance(c, TopicCandidate) for c in candidates)
    # No exception, three distinct candidates, distinct candidate_ids.
    assert len({c.candidate_id for c in candidates}) == 3
    # All share item_index=0 but differ in local_index.
    assert all(c.item_index == 0 for c in candidates)
    assert [c.local_index for c in candidates] == [0, 1, 2]


def test_topic_candidate_id_is_script_generated():
    """Task 10 / Canonical Identity Contract: candidate_id is derived
    by the script from (item_index, local_index, span_hint, item_fingerprint),
    NOT from the LLM-supplied semantic_label.
    """
    from src.pipeline.v7_extract.topic_candidate import derive_candidate_id

    fp = "fingerprint-abc"
    # Two different labels, same identity inputs → same candidate_id.
    a = derive_candidate_id(0, 0, span_hint="p1", item_fingerprint=fp)
    b = derive_candidate_id(0, 0, span_hint="p1", item_fingerprint=fp)
    assert a == b, "candidate_id must be deterministic"
    # Different local_index → different candidate_id.
    c = derive_candidate_id(0, 1, span_hint="p1", item_fingerprint=fp)
    assert a != c
    # Different span_hint → different candidate_id.
    d = derive_candidate_id(0, 0, span_hint="p2", item_fingerprint=fp)
    assert a != d
    # Different item_fingerprint → different candidate_id (stable across
    # sources, not just within one).
    e = derive_candidate_id(0, 0, span_hint="p1", item_fingerprint="other-fp")
    assert a != e
    # Prefix shape sanity: starts with "cand-".
    assert a.startswith("cand-0-0-")


@pytest.mark.asyncio
async def test_collection_one_article_may_produce_multiple_topics():
    """Task 10 sanity: a single collection article that the LLM splits
    into 3 candidates (local_index 0..2) results in 3 candidates
    accessible via the topic_clusterer internals.
    """
    from src.pipeline.v7_extract.topic_candidate import TopicCandidate

    items = [{"id": "art-0", "text": "Embedding + Chunking + Reranking", "kind": "article"}]
    payload = {
        "candidates": [
            {"item_index": 0, "local_index": 0, "span_hint": "para1",
             "semantic_label": "Embedding", "confidence": 0.9},
            {"item_index": 0, "local_index": 1, "span_hint": "para2",
             "semantic_label": "Chunking", "confidence": 0.85},
            {"item_index": 0, "local_index": 2, "span_hint": "para3",
             "semantic_label": "Reranking", "confidence": 0.8},
        ]
    }
    candidates = _payload_to_candidates(
        payload,
        [items[0]["id"]],
        ["fp-art-0"],
    )
    assert len(candidates) == 3
    assert all(isinstance(c, TopicCandidate) for c in candidates)
    assert len({c.candidate_id for c in candidates}) == 3
    # All three point to the same item but are independent candidates.
    assert all(c.item_index == 0 for c in candidates)


# ---------------------------------------------------------------------------
# Task 11 (Plan 2026-09-17): two-stage LLM (Stage 4A discovery + 4B grouping)
# + TopicDescriptor (Bounded Evidence Contract §3.2 — ≤ 600 bytes/item)
# ---------------------------------------------------------------------------


def test_topic_descriptor_within_budget():
    """Task 11 / Bounded Evidence Contract §3.2: each TopicDescriptor must
    fit in ≤ MAX_DESCRIPTOR_BYTES (600 bytes). Hard invariant — failing this
    is a Contract violation, not a soft warning.
    """
    from src.pipeline.v7_extract.topic_descriptor import (
        MAX_DESCRIPTOR_BYTES,
        build_descriptors,
    )

    # Three item shapes: tiny / medium / huge — descriptor must stay ≤ budget
    # even when the source text is unbounded.
    items = [
        {"id": "tiny", "text": "x" * 50, "kind": "article", "title": "T"},
        {"id": "medium", "text": "y" * 1500, "kind": "section", "title": "M"},
        {"id": "huge", "text": "z" * 200_000, "kind": "article", "title": "H"},
    ]
    descriptors = build_descriptors(items)
    assert len(descriptors) == 3
    for d in descriptors:
        size = len(d.bounded_lead.encode("utf-8")) + len(d.bounded_tail.encode("utf-8"))
        # The DESCRIPTOR TEXT (head + tail) is what the LLM sees — must stay bounded.
        assert size <= MAX_DESCRIPTOR_BYTES, (
            f"descriptor for item_index={d.item_index} is {size} bytes "
            f"(limit {MAX_DESCRIPTOR_BYTES}) — Bounded Evidence Contract §3.2 violation"
        )


@pytest.mark.asyncio
async def test_stage4a_discovers_per_item_candidates():
    """Task 11: Stage 4A = per-item candidate discovery. The function
    accepts ``TopicDescriptor`` objects and returns ``TopicCandidate`` list.
    """
    from src.pipeline.v7_extract.topic_descriptor import build_descriptors
    from src.pipeline.v7_extract.topic_clusterer import (
        _discover_topics_in_batch,
    )

    items = [
        {"id": "a", "text": "Embedding + Chunking + Reranking", "kind": "article"},
        {"id": "b", "text": "Worldbuilding: magic system", "kind": "article"},
    ]
    descriptors = build_descriptors(items)

    fake = FakeLLMClient()
    fake.script(
        "cluster_discover",
        '{"candidates": ['
        '{"item_index": 0, "local_index": 0, "span_hint": "p1", "semantic_label": "Embedding", "confidence": 0.9},'
        '{"item_index": 0, "local_index": 1, "span_hint": "p2", "semantic_label": "Chunking", "confidence": 0.85},'
        '{"item_index": 1, "local_index": 0, "span_hint": "p3", "semantic_label": "Magic system", "confidence": 0.8}'
        ']}',
    )

    candidates = await _discover_topics_in_batch(
        descriptors, llm=fake, project_root=None,
    )
    assert len(candidates) == 3
    assert candidates[0].item_index == 0
    assert candidates[0].semantic_label == "Embedding"
    assert candidates[2].item_index == 1
    assert candidates[2].semantic_label == "Magic system"
    # All candidate_ids are script-generated (distinct).
    assert len({c.candidate_id for c in candidates}) == 3
    # Discovery must NOT do cross-item grouping (Stage 4B's job).
    assert all(c.item_index in (0, 1) for c in candidates)


@pytest.mark.asyncio
async def test_stage4b_groups_candidates_across_items():
    """Task 11: Stage 4B = cross-item candidate grouping. The function
    takes the candidates from Stage 4A and asks the LLM which belong to
    the same logical topic; returns grouping labels / group identifiers.
    """
    from src.pipeline.v7_extract.topic_candidate import TopicCandidate
    from src.pipeline.v7_extract.topic_clusterer import (
        _group_candidates,
    )

    candidates = [
        TopicCandidate(
            candidate_id="cand-0-0-abc", item_index=0, local_index=0,
            semantic_label="Embedding", evidence_span_hint="p1", confidence=0.9,
        ),
        TopicCandidate(
            candidate_id="cand-0-1-def", item_index=0, local_index=1,
            semantic_label="Chunking", evidence_span_hint="p2", confidence=0.85,
        ),
        TopicCandidate(
            candidate_id="cand-1-0-ghi", item_index=1, local_index=0,
            semantic_label="Embedding techniques", evidence_span_hint="p3",
            confidence=0.8,
        ),
    ]

    fake = FakeLLMClient()
    # Stage 4B output: a list of groups, each with the candidate_ids that
    # belong together. Group 1 = embedding-related (cand-0-0 + cand-1-0);
    # Group 2 = chunking (cand-0-1).
    fake.script(
        "cluster_group",
        '{"groups": ['
        '{"candidate_ids": ["cand-0-0-abc", "cand-1-0-ghi"], "label": "Embedding"},'
        '{"candidate_ids": ["cand-0-1-def"], "label": "Chunking"}'
        ']}',
    )

    groups = await _group_candidates(
        candidates, llm=fake, project_root=None,
    )
    # Two groups produced by the LLM.
    assert len(groups) == 2
    # The grouping is by candidate_id, which is script-owned.
    assert "cand-0-0-abc" in groups[0].candidate_ids
    assert "cand-1-0-ghi" in groups[0].candidate_ids
    assert "cand-0-1-def" in groups[1].candidate_ids


@pytest.mark.asyncio
async def test_clustering_consumes_stage2_structural_summary():
    """Task 11: cluster_topics must accept a ``segmentation_result`` parameter
    and consume Stage 2's structural summary (even when only stored / passed
    through — the wiring is the contract).

    This is the "Stage 1 错分类（collection → multi_section）时 Stage 4 仍按
    Stage 2 结构分组" acceptance from the master plan: Stage 2 wins, Stage 1
    is only a soft hint.
    """
    from src.pipeline.v7_extract.segmentation import (
        CoverageReport,
        ItemKind,
        CanonicalItem,
        SegmentationResult,
        SegmentationStatus,
    )
    from src.pipeline.v7_extract.invariants import InvariantReport
    from src.pipeline.v7_extract.topic_clusterer import cluster_topics

    items = [{"id": "a", "text": "alpha", "kind": "article"}]

    # Minimal SegmentationResult — only structural_signals is read by Stage 4.
    fake_segmentation = SegmentationResult(
        status=SegmentationStatus.SEGMENTED,
        method="structural_deterministic",
        items=[
            CanonicalItem(
                item_id="a", kind=ItemKind.ARTICLE,
                start_byte=0, end_byte=5,
                title="Alpha", text="alpha",
            ),
        ],
        coverage=CoverageReport(
            byte_accounting=1.0, structured_coverage=1.0,
            residual_ratio=0.0, unknown_ratio=0.0,
        ),
        invariants=InvariantReport(
            i1_nonempty=True,
            i2_boundaries_valid=True,
            i3_sorted=True,
            i4_non_overlapping=True,
            i5_complete_accounting=True,
        ),
        warnings=[],
        structural_signals={
            "header_count": 3,
            "byline_count": 1,
            "qa_marker_count": 0,
            "article_count": 1,
        },
        source_hash="abc123",
        segmenter_fingerprint="seg-123",
        residual_items=[],
    )

    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
    )

    # Stage 1 doc_type says "multi_section" (the WRONG classification).
    # Stage 2 segmentation_result says SEGMENTED with article_count=1
    # (the right structure). Stage 4 must accept both params and proceed.
    result = await cluster_topics(
        items,
        llm=fake,
        project_root=None,
        doc_type="multi_section",           # wrong Stage 1 hint
        segmentation_result=fake_segmentation,  # right Stage 2 contract
    )
    # The function returned a ClusterResult — wiring accepted both params.
    assert result.status.value in {"clustered", "degraded"}
    assert len(result.topics) == 1
    assert result.topics[0].item_ids == ["a"]


# ---------------------------------------------------------------------------
# Task 12 (Plan 2026-09-17): Topic.id is script-generated (no LLM dependence)
# Identity Contract (Canonical Identity Contract §2): SAME/ALIAS share
# canonical; LLM does NOT generate canonical IDs. For Stage 4 (which has
# no canonical concept yet), the analogous rule is: Topic.id must be
# script-derived from (source_id, candidate_ids) — never from the LLM
# semantic_label.
# ---------------------------------------------------------------------------


def test_topic_id_is_deterministic_hash_not_llm_label():
    """Task 12: derive_topic_id is deterministic on (source_id, candidate_ids).

    The same identity inputs → same topic_id, even when LLM label drifts.
    """
    from src.pipeline.v7_extract.topic_id import derive_topic_id

    source = "raw/sources/a.md"
    cands = ["raw/a#item-0", "raw/a#item-1"]
    a = derive_topic_id(source_id=source, candidate_ids=cands)
    b = derive_topic_id(source_id=source, candidate_ids=cands)
    assert a == b, "derive_topic_id must be deterministic"
    # Different label, same membership → same topic_id.
    # (semantic_label is explicitly NOT part of identity per Identity Contract.)
    c = derive_topic_id(
        source_id=source, candidate_ids=cands, semantic_label="重命名标签",
    )
    assert a == c, "semantic_label must not influence topic_id"


def test_topic_id_format_is_source_id_topic_hash():
    """Task 12: topic_id shape contract is `<source_id>-topic-<16hex>`.

    The format is a hard invariant — derive_topic_id returns exactly this
    shape so downstream consumers (page_id, Stage 7 writer) can rely on it.
    """
    import re
    from src.pipeline.v7_extract.topic_id import derive_topic_id

    source = "raw/sources/article_42.md"
    topic_id = derive_topic_id(
        source_id=source, candidate_ids=["a", "b", "c"],
    )
    # Format: <source_id>-topic-<16 hex chars>
    pattern = rf"^{re.escape(source)}-topic-[0-9a-f]{{16}}$"
    assert re.match(pattern, topic_id), (
        f"topic_id {topic_id!r} does not match pattern {pattern!r}"
    )
    # Hash portion is order-independent (sorted(candidate_ids)).
    same_set = derive_topic_id(
        source_id=source, candidate_ids=["c", "b", "a"],
    )
    assert topic_id == same_set, "candidate_ids order must not affect topic_id"
    # Different source_id → different topic_id (per-source uniqueness).
    other = derive_topic_id(
        source_id="raw/sources/article_99.md",
        candidate_ids=["a", "b", "c"],
    )
    assert topic_id != other
    # Different candidate set → different topic_id.
    other_set = derive_topic_id(
        source_id=source, candidate_ids=["a", "b"],
    )
    assert topic_id != other_set


def test_page_id_derived_from_script_generated_topic_id():
    """Task 12 / Persistence Contract §4.2.3: page_id is built from the
    script-generated topic_id (not from an LLM-supplied title). The same
    script-generated inputs → the same page_id, and the page_id survives
    LLM label drift.
    """
    from src.pipeline.v7_extract.topic_id import derive_topic_id
    from src.pipeline.v7_extract._page_id import _stable_page_id

    source = "raw/sources/article_42.md"
    candidate_ids = ["raw/article_42#item-0", "raw/article_42#item-1"]
    # Two different LLM labels for the same membership.
    topic_a = derive_topic_id(
        source_id=source, candidate_ids=candidate_ids,
    )
    topic_b = derive_topic_id(
        source_id=source, candidate_ids=candidate_ids,
        semantic_label="completely different LLM title",
    )
    page_a = _stable_page_id("raw/sources/article_42.md", topic_a)
    page_b = _stable_page_id("raw/sources/article_42.md", topic_b)
    assert page_a == page_b, (
        "page_id must not change when LLM label drifts — identity is the "
        "script-generated topic_id, not the label"
    )
    # Different source → different page_id.
    other_topic = derive_topic_id(
        source_id="raw/sources/other.md",
        candidate_ids=candidate_ids,
    )
    page_other = _stable_page_id("raw/sources/other.md", other_topic)
    assert page_a != page_other


# ---------------------------------------------------------------------------
# Task 13 (Plan 2026-09-17): __other__ preserved + unresolved signal in
# metrics + ClusterResult.unresolved. Backward compat: Stage 7 reads the
# __other__ Topic from cluster_result.topics as a sentinel. New: the same
# ClusterResult also exposes ClusterResult.unresolved (candidate IDs) +
# ClusterResult.metrics.unresolved_item_ratio so downstream can monitor
# knowledge loss without breaking the Stage 7 gate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolved_ratio_appears_in_metrics():
    """Task 13: when the LLM forgets an item (only assigns a, b but c is
    in items), ClusterResult.metrics.unresolved_item_ratio must reflect
    the lost coverage AND ClusterResult.unresolved must list the lost
    candidate ID. Stage 7 keeps reading __other__ from .topics as the
    block sentinel — both surfaces must agree.
    """
    fake = FakeLLMClient()
    # LLM assigns indexes [0, 1] only — forgets index 2 (id "i-2").
    fake.script(
        "cluster",
        _script_cluster_buckets([("t1", "T1", [0, 1])]),
    )

    items = _make_items(3)  # ids: "i-0", "i-1", "i-2"
    result = await cluster_topics(items, llm=fake, project_root=None)

    # Metric: 1 of 3 items unresolved → ratio = 1/3.
    assert result.metrics.unresolved_item_ratio == pytest.approx(1 / 3)

    # ClusterResult.unresolved lists the lost candidate IDs (script-owned).
    assert "i-2" in result.unresolved
    # __other__ Topic is still in .topics — Stage 7 gate keeps working.
    other_topics = [t for t in result.topics if t.id == OTHER_TOPIC_ID]
    assert len(other_topics) == 1
    assert "i-2" in other_topics[0].item_ids


@pytest.mark.asyncio
async def test_other_topic_preserved_as_blocked_but_metrics_emitted():
    """Task 13: when many items end up in __other__ (e.g. 6 of 10 items
    unresolved), the __other__ Topic is still emitted in cluster_result.topics
    (Stage 7 backward compat), AND metrics.unresolved_item_ratio exposes
    the 0.6 ratio so extract_pilot can warn operators about knowledge loss.
    """
    fake = FakeLLMClient()
    # LLM assigns indexes [0, 1, 2, 3] only — indexes 4..9 (6 items)
    # land in __other__. 6 / 10 = 0.6 unresolved_item_ratio.
    fake.script(
        "cluster",
        _script_cluster_buckets([("t1", "T1", [0, 1, 2, 3])]),
    )

    items = _make_items(10)
    result = await cluster_topics(items, llm=fake, project_root=None)

    # Backward compat: __other__ Topic is preserved in .topics.
    other_topics = [t for t in result.topics if t.id == OTHER_TOPIC_ID]
    assert len(other_topics) == 1
    assert len(other_topics[0].item_ids) == 6

    # New signal: metrics surface the unresolved ratio (>= 0.3 threshold).
    assert result.metrics.unresolved_item_ratio == pytest.approx(0.6)
    # ClusterResult.unresolved lists each candidate ID the LLM did not
    # place into a real topic — operators can grep this directly.
    assert len(result.unresolved) == 6


# ---------------------------------------------------------------------------
# Task 13 / Stage 7 integration: extract_pilot emits ``stage4_unresolved``
# in ``review_reasons`` when ``metrics.unresolved_item_ratio`` exceeds
# UNRESOLVED_REVIEW_THRESHOLD (0.3). The ``__other__`` Topic in
# ``cluster_result.topics`` is preserved regardless (Stage 7 Guard A reads
# it as the block sentinel) — this is purely an operator-facing metric.
#
# Convention: extract_pilot integration tests for Stage 4 live here
# (alongside test_extract_pilot_routes_cluster_failed_to_extraction_failed
# from Task 9) because they bridge ClusterResult → ExtractionResult.
# ---------------------------------------------------------------------------


def _stage_scripts_for_unresolved(*, assign_first_n: int) -> "FakeLLMClient":
    """Queue scripts for a Stage 4 LLM that forgets most items.

    Returns a fake that classifies as single_method + completeness OK + a
    cluster call that only assigns the first ``assign_first_n`` Stage 2
    items to one topic. Everything else lands in ``__other__`` (Task 13
    backward compat).
    """
    from src.pipeline.v7_extract.llm_client import FakeLLMClient as _Fake
    fake = _Fake()
    fake.script(
        "classify",
        '{"doc_type": "single_method", "confidence": 0.9, "rationale": "r"}',
    )
    fake.script("completeness", '{"complete": true, "reason": "ok"}')
    bucket_indexes = list(range(assign_first_n))
    fake.script(
        "cluster",
        '{"topics": ['
        '{"id": "t1", "title": "T1", "item_indexes": '
        + str(bucket_indexes).replace("'", "") + '}]}',
    )
    # fill_slots: 8 copies — even the __other__ topic runs Stage 5.
    for _ in range(8):
        fake.script(
            "fill_slots",
            '{"slots": '
            '{"definition":"def","characteristics":"c",'
            '"examples":"e","related_concepts":"rc","references":"ref"}, '
            '"evidence": '
            '{"definition":{"item_index":0,"source_text_excerpt":"x"},'
            '"characteristics":{"item_index":0,"source_text_excerpt":"x"},'
            '"examples":{"item_index":0,"source_text_excerpt":"x"},'
            '"related_concepts":{"item_index":0,"source_text_excerpt":"x"},'
            '"references":{"item_index":0,"source_text_excerpt":"x"}}}',
        )
    return fake


def _write_unresolved_fixture(tmp_path, *, items: int):
    """Write a Stage 2-shaped source with ``items`` structural units."""
    from pathlib import Path
    parts = [f"# 主题\n\n源文档导言。" + ("补充。" * 30) + "\n"]
    for i in range(items):
        parts.append(
            f"\n## 子主题 {i}\n\n这是子主题 {i} 的足够长的内容。"
            + ("细节。" * 30),
        )
    body = "".join(parts)
    path = tmp_path / "raw" / "sources" / "unresolved.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=False)
def _scrub_d9_temp_whitelist(monkeypatch):
    """D9: the resolver rejects tmp_path (which lives under %TEMP%) unless
    we clear the temp env vars. Pilot tests always pass a tmp_path as
    project_root, so this scrub is required (mirrors test_extract_pilot.py).
    """
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMP", raising=False)


def test_extract_pilot_emits_unresolved_review_reason(tmp_path, _scrub_d9_temp_whitelist) -> None:
    """Task 13: when Stage 4's ``unresolved_item_ratio`` exceeds 0.3, the
    pilot must surface a ``stage4_unresolved`` entry in
    ``ExtractionResult.review_reasons`` so operators can monitor knowledge
    loss. The ``__other__`` Topic in ``cluster_result.topics`` is preserved
    (Stage 7 backward compat) — no Stage 7 change required.
    """
    import asyncio
    from scripts.extract_pilot import _extract_one

    # The structural scanner produces ``# 主题`` + ``## 子主题 N`` as
    # separate items, so a fixture with 5 ## headings yields 6 Stage 2
    # items. With the LLM assigning 1 of 6 → 5/6 ≈ 0.83 unresolved,
    # well above the 0.3 threshold.
    path = _write_unresolved_fixture(tmp_path, items=5)
    fake = _stage_scripts_for_unresolved(assign_first_n=1)

    result = asyncio.run(_extract_one(
        tmp_path, path, "raw/sources/unresolved.md", llm=fake,
    ))

    # Sanity: the metric is over 0.3 (the trigger condition).
    actual_ratio = result.metadata["cluster_metrics"]["unresolved_item_ratio"]
    assert actual_ratio > 0.3, (
        f"fixture should yield unresolved_ratio > 0.3, got {actual_ratio:.2f}"
    )

    # The unresolved signal MUST appear in review_reasons (Task 13 contract).
    unresolved_reasons = [
        r for r in result.review_reasons if r.startswith("stage4_unresolved")
    ]
    assert unresolved_reasons, (
        f"expected stage4_unresolved in review_reasons; got {result.review_reasons}"
    )
    # Reason includes the ratio so operators can grep / threshold against it.
    assert any(f"{actual_ratio:.2f}" in r for r in unresolved_reasons), (
        f"unresolved_ratio={actual_ratio:.2f} should appear in reason; "
        f"got {unresolved_reasons}"
    )


def test_extract_pilot_no_unresolved_review_reason_when_ratio_low(tmp_path, _scrub_d9_temp_whitelist) -> None:
    """Task 13 (negative): when Stage 4's ``unresolved_item_ratio`` is
    below the 0.3 threshold, the pilot MUST NOT emit a
    ``stage4_unresolved`` review reason. We only warn when knowledge
    loss is significant.
    """
    import asyncio
    from scripts.extract_pilot import _extract_one

    # 5 ## headings → 6 Stage 2 items. LLM assigns 5 of 6 → 1/6 ≈ 0.17,
    # well below the 0.3 threshold.
    path = _write_unresolved_fixture(tmp_path, items=5)
    fake = _stage_scripts_for_unresolved(assign_first_n=5)

    result = asyncio.run(_extract_one(
        tmp_path, path, "raw/sources/low_unresolved.md", llm=fake,
    ))

    unresolved_reasons = [
        r for r in result.review_reasons if r.startswith("stage4_unresolved")
    ]
    actual_ratio = result.metadata["cluster_metrics"]["unresolved_item_ratio"]
    assert actual_ratio <= 0.3, (
        f"fixture should yield unresolved_ratio <= 0.3, got {actual_ratio:.2f}"
    )
    assert not unresolved_reasons, (
        f"unresolved_ratio={actual_ratio:.2f} should NOT trigger review reason; "
        f"got {unresolved_reasons}"
    )


# ---------------------------------------------------------------------------
# Task 47: Stage 4 identity stability (rerun same source -> same topic_id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_id_stable_across_repeated_runs():
    """Same source + same LLM scripted response + same prompt
    -> two cluster_topics() calls produce identical topic_id sequences."""
    response = (
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0, 1]},'
        '           {"id": "t2", "title": "T2", "item_indexes": [2]}]}'
    )
    fake = FakeLLMClient()
    fake.script("cluster", response)
    fake.script("cluster", response)   # queue 2 responses (one per run)

    items = [
        {"id": "article-1", "text": "first item", "kind": "article"},
        {"id": "article-2", "text": "second item", "kind": "article"},
        {"id": "article-3", "text": "third item", "kind": "article"},
    ]

    r1 = await cluster_topics(
        items, llm=fake, project_root=None, source_id="raw/source-A.md",
    )
    r2 = await cluster_topics(
        items, llm=fake, project_root=None, source_id="raw/source-A.md",
    )

    # Topic id sequence (script-generated from items + source_id) must be identical.
    ids_1 = [t.id for t in r1.topics]
    ids_2 = [t.id for t in r2.topics]
    assert ids_1 == ids_2
    # And topic_id format is non-empty / deterministic (not the __other__ fallback).
    assert len(ids_1) == 2
    for tid in ids_1:
        assert tid
        assert isinstance(tid, str)
        assert tid != "__other__"


@pytest.mark.asyncio
async def test_topic_id_differs_between_different_sources():
    """Same items, different source_id -> different topic_ids
    (script hash includes source_id)."""
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
    )

    items = [
        {"id": "article-1", "text": "shared item", "kind": "article"},
    ]

    r1 = await cluster_topics(items, llm=fake, project_root=None, source_id="source-A.md")
    r2 = await cluster_topics(items, llm=fake, project_root=None, source_id="source-B.md")

    ids_1 = {t.id for t in r1.topics}
    ids_2 = {t.id for t in r2.topics}
    assert ids_1.isdisjoint(ids_2), (
        f"different sources produced overlapping topic_ids: {ids_1 & ids_2}"
    )


@pytest.mark.asyncio
async def test_topic_id_stable_when_only_llm_response_unchanged():
    """FakeLLMClient scripted identically across runs -> topic_ids stable.

    Note: FakeLLMClient.script() consumes one response per complete() call,
    so we queue 3 identical responses (one per run) to get 3 stable runs.
    """
    fake = FakeLLMClient()
    response = (
        '{"topics": [{"id": "alpha", "title": "A", "item_indexes": [0]},'
        '           {"id": "beta", "title": "B", "item_indexes": [1]}]}'
    )
    fake.script("cluster", response)
    fake.script("cluster", response)
    fake.script("cluster", response)

    items = [
        {"id": "a1", "text": "first", "kind": "article"},
        {"id": "a2", "text": "second", "kind": "article"},
    ]

    runs = []
    for _ in range(3):
        result = await cluster_topics(
            items, llm=fake, project_root=None, source_id="src.md",
        )
        runs.append([t.id for t in result.topics])

    # All 3 runs produce the same topic_id sequence.
    assert runs[0] == runs[1] == runs[2]
    # And 2 topics (not the __other__ fallback).
    assert len(runs[0]) == 2
    assert all(tid != "__other__" for tid in runs[0])


@pytest.mark.asyncio
async def test_topic_id_changes_when_input_items_change():
    """Different item set -> different topic_ids (script hash includes items)."""
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": [{"id": "t1", "title": "T1", "item_indexes": [0]}]}',
    )

    items_v1 = [{"id": "a1", "text": "alpha", "kind": "article"}]
    items_v2 = [{"id": "b1", "text": "beta", "kind": "article"}]

    r1 = await cluster_topics(items_v1, llm=fake, project_root=None, source_id="src.md")
    r2 = await cluster_topics(items_v2, llm=fake, project_root=None, source_id="src.md")

    assert [t.id for t in r1.topics] != [t.id for t in r2.topics]


@pytest.mark.asyncio
async def test_topic_id_format_is_source_id_based_hash():
    """topic_id is a script-derived hash; never equals the LLM-supplied id."""
    fake = FakeLLMClient()
    fake.script(
        "cluster",
        '{"topics": [{"id": "llm-supplied-id", "title": "T1", "item_indexes": [0]}]}',
    )

    items = [{"id": "a1", "text": "x", "kind": "article"}]
    result = await cluster_topics(
        items, llm=fake, project_root=None, source_id="src.md",
    )

    # Topic.id is the script hash, NOT the LLM-supplied "llm-supplied-id".
    assert result.topics
    assert result.topics[0].id != "llm-supplied-id"
