"""Task 28 — Candidate retrieval 6 strategies.

Five RED probes (each a contract assertion):

  * test_retrieval_returns_top_n_candidates — top-N ordering + dedup
  * test_acronym_match_finds_RAG_alias       — strategy 4 (acronym)
  * test_embedding_similarity_only_signals_worth_comparing_not_merge
                                              — strategy 6 (vector_neighbor)
                                                with threshold gate
  * test_vector_neighbor_retrieval_integration — F10 整改要求
  * test_vector_neighbor_performance_under_10k_canonical — F10 硬指标 < 100ms

The first three exercise the cheap textual signals (wikilink /
Jaccard / lexical / acronym / alias). The last two are the F10
hard requirement: ``vector_neighbor`` ships in v1 and stays
under 100ms with 10k canonical concepts.

Contract summary (see candidate_retrieval.py docstring):
    MAX_CANDIDATES = 20
    VECTOR_NEIGHBOR_THRESHOLD = 0.7
    Sort: score desc, then canonical_id asc. Cap at max_candidates.
    Strategy values: "explicit" / "entity_overlap" / "lexical" /
                     "acronym" / "alias" / "vector_neighbor".
"""
from __future__ import annotations


def test_retrieval_returns_top_n_candidates():
    """retrieve_candidates returns at most max_candidates + deterministic ordering.

    - ``cid_a`` (Machine Learning) matches via shared tokens ("machine learning").
    - ``cid_b`` (Beta) matches via explicit ``[[Beta]]`` wikilink (score 1.0).
    - ``cid_c`` (Cooking) has zero overlap with the new page body.
    - Dedup keeps the best score per canonical_id; explicit ranks first.
    """
    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        retrieve_candidates,
    )
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        new_canonical_id,
    )

    cid_a = new_canonical_id()
    cid_b = new_canonical_id()
    cid_c = new_canonical_id()

    concepts = [
        CanonicalConcept(
            canonical_id=cid_a,
            preferred_label="Machine Learning",
            member_page_ids=["page-a"],
            aliases=[],
        ),
        CanonicalConcept(
            canonical_id=cid_b,
            preferred_label="Beta",
            member_page_ids=["page-b"],
            aliases=[],
        ),
        CanonicalConcept(
            canonical_id=cid_c,
            preferred_label="Cooking",
            member_page_ids=["page-c"],
            aliases=[],
        ),
    ]
    index = CanonicalIndex.build(
        concepts,
        body_by_page={
            "page-a": "machine learning algorithms and neural networks",
            "page-b": "totally different content here",
            "page-c": "kitchen recipes and food",
        },
    )

    candidates = retrieve_candidates(
        "new-page",
        "machine learning basics [[Beta]]",
        "New Page",
        index,
        max_candidates=5,
    )
    canon_ids = [c.canonical_id for c in candidates]
    assert cid_a in canon_ids
    assert cid_b in canon_ids
    assert cid_c not in canon_ids

    by_id = {c.canonical_id: c for c in candidates}
    # explicit wikilink (score 1.0) ranks >= token overlap (jaccard < 1.0)
    assert by_id[cid_b].score >= by_id[cid_a].score
    # and the explicit candidate should be at or near the very top
    assert candidates[0].canonical_id == cid_b


def test_acronym_match_finds_RAG_alias():
    """Acronym strategy matches ``RAG`` against ``Retrieval-Augmented Generation``.

    The page body contains the upper-case token "RAG" (2-6 chars).
    The canonical's preferred label is the multi-word phrase whose
    initial letters spell ``R-A-G``. Either the ``acronym`` strategy or
    the ``alias`` strategy must surface this canonical — both are valid
    because the spec also accepts "RAG" as an explicit alias.
    """
    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        retrieve_candidates,
    )
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        new_canonical_id,
    )

    cid = new_canonical_id()
    concepts = [
        CanonicalConcept(
            canonical_id=cid,
            preferred_label="Retrieval-Augmented Generation",
            member_page_ids=["page-rag"],
            aliases=["RAG"],
        ),
    ]
    index = CanonicalIndex.build(concepts)
    candidates = retrieve_candidates(
        "new",
        "We use RAG for retrieval augmented generation tasks",
        "RAG Page",
        index,
    )
    target_ids = [c.canonical_id for c in candidates]
    assert cid in target_ids
    strategies = {c.strategy for c in candidates if c.canonical_id == cid}
    assert "acronym" in strategies or "alias" in strategies


def test_embedding_similarity_only_signals_worth_comparing_not_merge():
    """vector_neighbor is a "worth comparing" signal, gated by threshold.

    - Query is nearly identical to ``cid_a`` (cosine ~ 0.99 → above
      threshold → surfaced).
    - Query is orthogonal to ``cid_b`` (cosine ~ 0.0 → below
      threshold → excluded).
    The retrieval layer enforces the gate; the LLM resolver (Task 29)
    decides whether the result is the same concept.
    """
    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        retrieve_candidates,
        VECTOR_NEIGHBOR_THRESHOLD,
    )
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        new_canonical_id,
    )

    cid_a = new_canonical_id()
    cid_b = new_canonical_id()
    concepts = [
        CanonicalConcept(
            canonical_id=cid_a,
            preferred_label="A",
            member_page_ids=["p1"],
            aliases=[],
        ),
        CanonicalConcept(
            canonical_id=cid_b,
            preferred_label="B",
            member_page_ids=["p2"],
            aliases=[],
        ),
    ]
    index = CanonicalIndex.build(concepts)
    index.register_vector(cid_a, [1.0, 0.0, 0.0], "stub")
    index.register_vector(cid_b, [0.0, 1.0, 0.0], "stub")
    query = [0.99, 0.01, 0.0]

    candidates = retrieve_candidates(
        "q",
        "no text",
        "Q",
        index,
        query_embedding=query,
        embedding_model_id="stub",
    )
    target_ids = {c.canonical_id: c for c in candidates}

    # cid_a has cosine ≈ 0.99 → above threshold → surfaced
    assert cid_a in target_ids
    # cid_b has cosine ≈ 0.01 → below threshold → either absent or sub-threshold
    if cid_b in target_ids:
        assert target_ids[cid_b].score < VECTOR_NEIGHBOR_THRESHOLD


def test_vector_neighbor_retrieval_integration():
    """F10 整改要求 — vector_neighbor is in v1; cosine ≥ threshold surfaces it."""
    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        retrieve_candidates,
        VECTOR_NEIGHBOR_THRESHOLD,
    )
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        new_canonical_id,
    )

    cid = new_canonical_id()
    concepts = [
        CanonicalConcept(
            canonical_id=cid,
            preferred_label="X",
            member_page_ids=["p"],
            aliases=[],
        ),
    ]
    index = CanonicalIndex.build(concepts)
    index.register_vector(cid, [1.0, 0.0, 0.0], "stub")

    # Identical vector → cosine = 1.0
    candidates = retrieve_candidates(
        "q",
        "no text",
        "Q",
        index,
        query_embedding=[1.0, 0.0, 0.0],
        embedding_model_id="stub",
    )
    target_ids = [c.canonical_id for c in candidates]
    assert cid in target_ids
    by_id = {c.canonical_id: c for c in candidates}
    assert by_id[cid].strategy == "vector_neighbor"
    assert by_id[cid].score >= VECTOR_NEIGHBOR_THRESHOLD


def test_vector_neighbor_performance_under_10k_canonical():
    """F10 硬指标 — retrieval < 100ms with 10k canonical concepts.

    1536-dim vectors (matching the project LanceDB schema). Only 100 of
    the 10k concepts have a registered vector (the rest get filtered
    out by the cache lookup), and the rest of the surface area
    (explicit / overlap / lexical / acronym / alias) is empty for
    a body of ``"no text"``. The full scan stays under 100ms.
    """
    import time

    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        retrieve_candidates,
    )
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        new_canonical_id,
    )

    N = 10_000
    concepts = []
    for i in range(N):
        cid = new_canonical_id()
        concepts.append(
            CanonicalConcept(
                canonical_id=cid,
                preferred_label=f"C{i}",
                member_page_ids=[f"p{i}"],
                aliases=[],
            )
        )
    index = CanonicalIndex.build(concepts)
    # Register only 100 vectors (the rest don't need them — we just
    # need the cache scan path exercised over 10k entries).
    for c in concepts[:100]:
        vec_value = float(hash(c.canonical_id) % 100) / 100.0
        index.register_vector(c.canonical_id, [vec_value] * 1536, "stub")

    query = [0.5] * 1536

    start = time.perf_counter()
    candidates = retrieve_candidates(
        "q",
        "no text",
        "Q",
        index,
        query_embedding=query,
        embedding_model_id="stub",
        max_candidates=20,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Sanity: at least the 100 registered candidates could surface;
    # the cap holds at 20.
    assert len(candidates) <= 20

    assert elapsed_ms < 100, (
        f"10k canonical retrieval took {elapsed_ms:.1f}ms, exceeds 100ms"
    )