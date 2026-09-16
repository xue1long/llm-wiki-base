from __future__ import annotations

from src.pipeline.v7_extract.llm_client import FakeLLMClient
from src.pipeline.v7_extract.relation_extractor import (
    PageRelation,
    extract_relations,
)
from src.pipeline.v7_extract.slot_filler import (
    CONCEPT_SLOTS,
    ConceptPage,
    Slot,
    SlotEvidence,
)
from src.pipeline.v7_extract import relation_models, relation_ontology
from src.pipeline.v7_extract.wiki_writer import WikiWriter


def _page(page_id: str, title: str, *, related: str = "", characteristics: str = "") -> ConceptPage:
    slots = {name: "来源内容" for name in CONCEPT_SLOTS}
    slots["related_concepts"] = related
    slots["characteristics"] = characteristics or "核心特征"
    return ConceptPage(page_id, title, slots, [f"source-{page_id}"])


def _writable_page(page_id: str, source: str) -> ConceptPage:
    """Build a ConceptPage that survives WikiWriter's three gates (P4 /
    needs_review / has_evidence). Mirrors the helper in
    ``test_v7_extract_stage7.py`` so the F8 best-effort frontmatter
    regression test exercises real writer semantics.
    """
    slots = {name: f"{name} 内容" for name in CONCEPT_SLOTS}
    slot_evidence = {
        name: Slot(
            name=name,
            body=slots[name],
            evidence=SlotEvidence(
                item_id=source,
                source_text_excerpt="...",
                has_evidence=True,
                needs_review=False,
            ),
            needs_review=False,
        )
        for name in CONCEPT_SLOTS
    }
    return ConceptPage(
        id=page_id,
        title=f"标题-{page_id}",
        slots=slots,
        sources=[source],
        slot_evidence=slot_evidence,
        needs_review_slots=(),
        topic_id=page_id,
    )


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


# ---------------------------------------------------------------------------
# Task 23 — Stage 6R RelationPredicate ontology + RelationKey
# ---------------------------------------------------------------------------


def test_relation_predicate_enum_matches_wiki_ontology() -> None:
    """Enum covers 8 directional + 4 symmetric predicates + UNRESOLVED
    catch-all (13 members total); is_known / coerce behavior.

    is_known excludes UNRESOLVED (LLM catch-all) and any garbage string.
    coerce returns UNRESOLVED on garbage rather than raising.
    """
    assert len(list(relation_ontology.RelationPredicate)) == 13
    # 12 substantive predicates + UNRESOLVED catch-all.
    expected = {
        "refines",
        "supported_by",
        "causes",
        "requires",
        "contradicts",
        "extends",
        "depends_on",
        "instance_of",
        "related_to",
        "similar_to",
        "co_occurs_with",
        "paired_with",
        "unresolved",
    }
    assert {p.value for p in relation_ontology.RelationPredicate} == expected
    # Directional vs symmetric split (8 directional, 4 symmetric, 1
    # catch-all — UNRESOLVED is neither directional nor symmetric).
    directional = sum(
        1 for p in relation_ontology.RelationPredicate
        if relation_ontology.get_spec(p).directional
    )
    symmetric = sum(
        1 for p in relation_ontology.RelationPredicate
        if relation_ontology.get_spec(p).symmetric
    )
    assert directional == 8
    assert symmetric == 4

    # is_known: substantive predicate is known, UNRESOLVED + garbage are not.
    assert relation_ontology.is_known("refines") is True
    assert relation_ontology.is_known("related_to") is True
    assert relation_ontology.is_known("unresolved") is False
    assert relation_ontology.is_known("garbage_predicate") is False
    assert relation_ontology.is_known("") is False

    # coerce: substantive predicates round-trip; garbage falls to UNRESOLVED.
    assert (
        relation_ontology.coerce("refines")
        is relation_ontology.RelationPredicate.REFINES
    )
    assert (
        relation_ontology.coerce("related_to")
        is relation_ontology.RelationPredicate.RELATED_TO
    )
    assert (
        relation_ontology.coerce("garbage")
        is relation_ontology.RelationPredicate.UNRESOLVED
    )
    assert (
        relation_ontology.coerce("")
        is relation_ontology.RelationPredicate.UNRESOLVED
    )


def test_relation_key_canonicalizes_symmetric_relations() -> None:
    """Symmetric predicates collapse (A,B) and (B,A); directional keep order."""
    # Symmetric: related_to
    k1 = relation_models.RelationKey(
        "page-a", relation_ontology.RelationPredicate.RELATED_TO, "page-b"
    )
    k2 = relation_models.RelationKey(
        "page-b", relation_ontology.RelationPredicate.RELATED_TO, "page-a"
    )
    assert k1.canonical() == k2.canonical()
    assert k1.relation_id() == k2.relation_id()

    # Symmetric: similar_to, co_occurs_with, paired_with all behave the same.
    for pred in (
        relation_ontology.RelationPredicate.SIMILAR_TO,
        relation_ontology.RelationPredicate.CO_OCCURS_WITH,
        relation_ontology.RelationPredicate.PAIRED_WITH,
    ):
        forward = relation_models.RelationKey("page-a", pred, "page-b")
        reverse = relation_models.RelationKey("page-b", pred, "page-a")
        assert forward.canonical() == reverse.canonical()
        assert forward.relation_id() == reverse.relation_id()

    # Directional: refines / depends_on / etc. preserve source→target order.
    for pred in (
        relation_ontology.RelationPredicate.REFINES,
        relation_ontology.RelationPredicate.DEPENDS_ON,
        relation_ontology.RelationPredicate.CAUSES,
    ):
        forward = relation_models.RelationKey("page-a", pred, "page-b")
        reverse = relation_models.RelationKey("page-b", pred, "page-a")
        assert forward.canonical() != reverse.canonical()
        assert forward.relation_id() != reverse.relation_id()


def test_relation_id_is_deterministic_hash() -> None:
    """Same (source, predicate, target) → identical relation_id across calls."""
    k = relation_models.RelationKey(
        "a", relation_ontology.RelationPredicate.REFINES, "b"
    )
    rid = k.relation_id()
    assert rid.startswith("rel-")
    assert len(rid) == len("rel-") + 12  # rel- + 12 hex (sha1[:12])

    # Same inputs → same hash.
    k2 = relation_models.RelationKey(
        "a", relation_ontology.RelationPredicate.REFINES, "b"
    )
    assert k2.relation_id() == rid

    # Different inputs → different hash.
    k3 = relation_models.RelationKey(
        "a", relation_ontology.RelationPredicate.REFINES, "c"
    )
    assert k3.relation_id() != rid

    # Canonical form drives relation_id (so symmetric flip → same id).
    fwd = relation_models.RelationKey(
        "page-a", relation_ontology.RelationPredicate.RELATED_TO, "page-b"
    )
    rev = relation_models.RelationKey(
        "page-b", relation_ontology.RelationPredicate.RELATED_TO, "page-a"
    )
    assert fwd.relation_id() == rev.relation_id()


def test_relations_remain_in_wiki_frontmatter_as_best_effort_view(tmp_path) -> None:
    """F8 decision fallback: WikiWriter still writes ``relations:`` to
    frontmatter. The RelationStore (Task 24) will be the authoritative
    source — but the legacy frontmatter view stays intact so existing
    readers don't break.
    """
    writer = WikiWriter(tmp_path)
    pages = [_writable_page("concept-a", "raw-a"), _writable_page("concept-b", "raw-a")]
    relations = [PageRelation("concept-b", "concept-a", "refines")]
    report = writer.commit_and_index(pages, relations)

    # Sanity: writer actually wrote both pages.
    assert set(report.written) == {"concept-a", "concept-b"}

    page_a = (tmp_path / "wiki" / "concepts" / "concept-a.md").read_text(
        encoding="utf-8"
    )
    page_b = (tmp_path / "wiki" / "concepts" / "concept-b.md").read_text(
        encoding="utf-8"
    )

    # ``relations:`` field exists in the frontmatter of the source page.
    assert "relations:" in page_b
    assert "refines" in page_b
    assert "concept-a" in page_b  # target reference

    # concept-a is a target only — its own frontmatter has no ``relations:``
    # block (empty relations list is still a key, but the page is not a
    # source of any edge in this batch).
    assert "concept-a" in page_a
    # The target page either has no relations key or has an empty list.
    if "relations:" in page_a:
        # If the key is emitted, it must be empty (no outgoing edges).
        after = page_a.split("relations:", 1)[1]
        # Stop at the next YAML key (lines starting at column 0) or the
        # frontmatter closer.
        section = after.split("\n", 1)[0]
        assert section.strip() in ("[]", "")


# ---------------------------------------------------------------------------
# Task 24 — Stage 6R RelationStore + independent checkpoint
# ---------------------------------------------------------------------------


def test_relation_store_persists_per_page(tmp_path) -> None:
    """RelationStore.apply_result writes the run-state + event log, and
    get_run_record / list_page_relations read back what was written.
    """
    from src.pipeline.v7_extract.relation_store import (
        RelationRunRecord,
        RelationRunStatus,
        RelationStore,
    )

    store = RelationStore(tmp_path, extractor_fingerprint="fp-1")
    record = RelationRunRecord(
        page_id="p1",
        page_revision="rev-1",
        relation_ids=["rel-aaa", "rel-bbb"],
        status=RelationRunStatus.READY,
        extractor_fingerprint="fp-1",
        updated_at_ms=1000,
    )
    store.apply_result(record)

    # Both index files were created.
    assert (tmp_path / ".index" / "relation_run_state.json").exists()
    assert (tmp_path / ".index" / "relations.jsonl").exists()

    # Round-trip: get_run_record returns the record we wrote.
    fetched = store.get_run_record("p1")
    assert fetched == record

    # list_page_relations returns the relation_ids, sorted, no tombstone.
    assert store.list_page_relations("p1") == ["rel-aaa", "rel-bbb"]


def test_cascade_page_delete_tombstones_edges(tmp_path) -> None:
    """cascade_page_delete tombstones every relation whose source OR target
    is the deleted page. Tombstone events land in relations.jsonl; the
    deleted page's relation list collapses to empty; unrelated pages are
    untouched.
    """
    from src.pipeline.v7_extract.relation_store import (
        RelationRunRecord,
        RelationRunStatus,
        RelationStore,
    )

    store = RelationStore(tmp_path)
    store.apply_result(
        RelationRunRecord(
            page_id="p1",
            page_revision="r1",
            relation_ids=["rel-aaa", "rel-bbb"],
            status=RelationRunStatus.READY,
        )
    )
    store.apply_result(
        RelationRunRecord(
            page_id="p2",
            page_revision="r1",
            relation_ids=["rel-ccc"],
            status=RelationRunStatus.READY,
        )
    )

    store.cascade_page_delete("p1")

    # p1's relations are gone from the live view.
    assert store.list_page_relations("p1") == []

    # The event log has a tombstone line that mentions at least one of
    # p1's relation ids.
    jsonl = (tmp_path / ".index" / "relations.jsonl").read_text(encoding="utf-8")
    assert '"event": "tombstone"' in jsonl
    assert "rel-aaa" in jsonl

    # p2 is unaffected.
    assert store.list_page_relations("p2") == ["rel-ccc"]


def test_page_update_triggers_relation_recompute(tmp_path) -> None:
    """find_stale returns page_ids whose run record's page_revision no
    longer matches the wiki revision — these are the pages whose
    relations need to be re-run.
    """
    from src.pipeline.v7_extract.relation_store import (
        RelationRunRecord,
        RelationRunStatus,
        RelationStore,
    )

    store = RelationStore(tmp_path)
    store.apply_result(
        RelationRunRecord(
            page_id="p1",
            page_revision="rev-old",
            relation_ids=["rel-aaa"],
            status=RelationRunStatus.READY,
        )
    )
    store.apply_result(
        RelationRunRecord(
            page_id="p2",
            page_revision="rev-stable",
            relation_ids=["rel-bbb"],
            status=RelationRunStatus.READY,
        )
    )

    # Simulate the wiki updating p1's revision but not p2's.
    current = {"p1": "rev-new", "p2": "rev-stable"}
    stale = store.find_stale(current)

    assert stale == ["p1"]
    assert "p2" not in stale


# ---------------------------------------------------------------------------
# Task 25 — Stage 6R candidate retrieval + LLM-controlled predicate ontology
# ---------------------------------------------------------------------------


def _make_page(page_id: str, title: str, body: str):
    """Minimal duck-typed page object exposing ``id`` / ``title`` / ``body``."""

    class _P:
        pass

    p = _P()
    p.id = page_id
    p.title = title
    p.body = body
    return p


def test_candidate_retrieval_returns_top_n() -> None:
    """retrieve_candidates returns at most ``max_candidates`` rows and is
    deterministic: the EXPLICIT [[b]] wikilink ranks first with score=1.0."""
    from src.pipeline.v7_extract.candidate_retrieval import (
        MAX_CANDIDATES_PER_PAGE,
        PageIndex,
        retrieve_candidates,
    )

    pages = [
        _make_page(
            "a",
            "Alpha concept",
            "discusses [[b]] and explores retrieval augmentation methods",
        ),
        _make_page("b", "Beta concept", "no links here"),
        _make_page(
            "c",
            "Gamma retrieval augmentation overview",
            "introduces retrieval augmentation concepts and discusses methods",
        ),
    ]
    index = PageIndex.build(pages)
    candidates = retrieve_candidates("a", index, max_candidates=2)

    assert len(candidates) == 2
    # The constant must match the spec (used as the global cap).
    assert MAX_CANDIDATES_PER_PAGE == 30
    # Top-1 must be the explicit [[b]] wikilink — score=1.0, EXPLICIT kind.
    assert candidates[0].target_page_id == "b"
    assert candidates[0].kind == relation_models.RelationSupportKind.EXPLICIT
    assert candidates[0].score == 1.0
    # Determinism: scores are non-increasing (ties broken by target_page_id asc).
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_llm_cannot_invent_predicate() -> None:
    """LLM emits an unknown predicate → RelationSupportStatus.UNRESOLVED,
    not a hard error. Each edge (including the unknown-predicate one)
    still produces a RelationAssertion so the review queue keeps the
    evidence trail."""
    from src.pipeline.v7_extract import candidate_retrieval
    from src.pipeline.v7_extract.candidate_retrieval import (
        parse_llm_edges,
        render_llm_prompt,
    )

    raw = (
        '{"edges": ['
        '{"target": "b", "predicate": "refines", "context": "ok"},'
        '{"target": "c", "predicate": "made_up_predicate_xyz", "context": "bad"},'
        '{"target": "d", "predicate": "causes", "context": "ok"}'
        "]}"
    )

    pages = [
        _make_page("a", "Alpha", ""),
        _make_page("b", "Beta", ""),
        _make_page("c", "Gamma", ""),
        _make_page("d", "Delta", ""),
    ]
    # We don't actually call render_llm_prompt here (covered separately);
    # we only assert the prompt renders without raising.
    _ = render_llm_prompt(
        pages[0],
        [
            candidate_retrieval.RetrievalCandidate(
                target_page_id="b",
                score=1.0,
                kind=relation_models.RelationSupportKind.EXPLICIT,
                detail="wikilink",
            ),
            candidate_retrieval.RetrievalCandidate(
                target_page_id="c",
                score=0.9,
                kind=relation_models.RelationSupportKind.INFERRED,
                detail="jaccard",
            ),
            candidate_retrieval.RetrievalCandidate(
                target_page_id="d",
                score=0.8,
                kind=relation_models.RelationSupportKind.INFERRED,
                detail="lexical",
            ),
        ],
    )

    candidates = [
        candidate_retrieval.RetrievalCandidate(
            target_page_id="b",
            score=1.0,
            kind=relation_models.RelationSupportKind.EXPLICIT,
            detail="wikilink",
        ),
        candidate_retrieval.RetrievalCandidate(
            target_page_id="c",
            score=0.9,
            kind=relation_models.RelationSupportKind.INFERRED,
            detail="jaccard",
        ),
        candidate_retrieval.RetrievalCandidate(
            target_page_id="d",
            score=0.8,
            kind=relation_models.RelationSupportKind.INFERRED,
            detail="lexical",
        ),
    ]

    assertions = parse_llm_edges(
        raw,
        source_page_id="a",
        candidates=candidates,
        extractor_fingerprint="fp-test",
    )

    # All 3 edges produce a RelationAssertion (no exceptions).
    assert len(assertions) == 3
    by_target = {a.key.target_page_id: a for a in assertions}

    # Known predicates → SUPPORTED.
    assert by_target["b"].support_status == relation_models.RelationSupportStatus.SUPPORTED
    assert by_target["d"].support_status == relation_models.RelationSupportStatus.SUPPORTED

    # The invented predicate → UNRESOLVED status + UNRESOLVED predicate
    # (coerce() falls back to the catch-all member).
    assert by_target["c"].support_status == relation_models.RelationSupportStatus.UNRESOLVED
    assert (
        by_target["c"].key.predicate
        is relation_ontology.RelationPredicate.UNRESOLVED
    )

    # Every assertion carries the script-owned fingerprint (so reviewers
    # can tell which extractor produced the row).
    for a in assertions:
        assert a.extractor_fingerprint == "fp-test"
        assert a.support_kind == relation_models.RelationSupportKind.LLM_DIRECT


def test_explicit_vs_inferred_kind_distinguished() -> None:
    """The 3 retrieval categories populate ``RetrievalCandidate.kind``
    correctly: wikilinks → EXPLICIT, entity-overlap → INFERRED."""
    from src.pipeline.v7_extract.candidate_retrieval import (
        PageIndex,
        retrieve_candidates,
    )

    pages = [
        _make_page("a", "Alpha", "links to [[b]] explicitly"),
        _make_page("b", "Beta", "different content"),
        _make_page("c", "Concept Alpha Method", "shares alpha words"),
    ]
    index = PageIndex.build(pages)
    candidates = retrieve_candidates("a", index)

    by_target = {c.target_page_id: c for c in candidates}

    # The [[b]] link is explicit (always wins with score=1.0).
    assert "b" in by_target
    assert by_target["b"].kind == relation_models.RelationSupportKind.EXPLICIT
    assert by_target["b"].score == 1.0

    # The high-overlap sibling should be present and tagged INFERRED
    # (entity Jaccard). We don't pin the exact score — only the kind.
    if "c" in by_target:
        assert by_target["c"].kind == relation_models.RelationSupportKind.INFERRED
