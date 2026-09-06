"""Acceptance contract for the novel-wiki book-series compile-enable plan.

Plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md
Slice S0: synthetic writing-craft fixture + NOVEL_WIKI_PROFILE → decision=proceed.
Slice S0b: real novel-wiki writing-craft has ≥1 non-namespace edge.
"""
from __future__ import annotations

import pytest

from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import (
    GovernanceConfig,
    ReaderProfile,
    evaluate_series_gate,
)


# ─── fixtures ──────────────────────────────────────────────────────────


def _page(pid: str, *, page_type: str = "concept", taxonomy: str = "写作技法",
          source: bool = True, rels=()) -> PageRecord:
    return PageRecord(
        page_id=pid, title=pid, page_type=page_type,
        path=f"concepts/{pid}.md", primary_taxonomy=taxonomy,
        summary="summary",
        content_blocks=(ContentBlock(f"{pid}:0", pid, "Heading", f"body of {pid}", 0),),
        relation_targets=rels, content_sha256=f"hash-{pid}",
        char_count=100, token_count=None,
        sources=(f"source-{pid}",) if source else (),
    )


def _writing_craft_synthetic(*, n_concept: int = 30, n_synthesis: int = 1) -> list[PageRecord]:
    """Build a synthetic 写作技法 snapshot mirroring real-wiki shape.

    Real wiki has 540 concept + 1 synthesis + 0 entity. We scale to 30 + 1
    for fast tests but keep the type distribution.
    """
    pages: list[PageRecord] = []
    for i in range(n_concept):
        pages.append(_page(f"wc-c{i}", page_type="concept", taxonomy="写作技法"))
    for i in range(n_synthesis):
        # synthesis page is also reachable from concept pages via supports edge
        pages.append(_page(f"wc-s{i}", page_type="synthesis", taxonomy="写作技法"))
    # Add in-candidate supports edges: each concept → first synthesis
    if n_synthesis:
        first_synth = f"wc-s0"
        for i in range(n_concept):
            pages[i] = PageRecord(**{**pages[i].__dict__,
                "relation_targets": (("supports", first_synth),)})
    return pages


def _writing_craft_with_namespace() -> list[PageRecord]:
    """Build a writing-craft snapshot with only namespace edges (taxonomy_of).

    This is the *insufficient* case — even after relax, no learning edge exists.
    """
    pages = [_page(f"wc-c{i}") for i in range(5)]
    pages.append(_page("wc-s0", page_type="synthesis"))
    for p in pages:
        # only namespace edges
        ns_rels = (("taxonomy_of", "taxonomy-写作技法"),)
        p.__dict__["relation_targets"] = ns_rels
    return pages


def _snapshot(*pages: PageRecord) -> WikiSnapshot:
    return WikiSnapshot("snap-test", "/tmp/wiki", "wiki-v3", tuple(pages), ())


# ─── S0: synthetic fixture drives proceed ─────────────────────────────


def test_synthetic_writing_craft_with_relaxed_profile_drives_proceed() -> None:
    """With a synthetic writing-craft snapshot (concept-heavy, 1 synthesis,
    supports→synthesis edges) and the relaxed NOVEL_WIKI_PROFILE, the gate
    must classify at least one candidate as decision=proceed with
    closure_status=closed."""
    from src.kc.views.book.wiki.profiles import (
        NOVEL_WIKI_PROFILE,
        derive_chapter_exit_evidence,
    )

    pages = _writing_craft_synthetic(n_concept=30, n_synthesis=1)
    snap = _snapshot(*pages)
    # Synthesize the per-run profile: take NOVEL_WIKI_PROFILE defaults and
    # populate chapter_exit_evidence with the candidate's synthesis page_ids.
    exit_evidence = derive_chapter_exit_evidence(snap, "写作技法")
    profile = ReaderProfile(
        profile_id=NOVEL_WIKI_PROFILE.profile_id,
        task_types=NOVEL_WIKI_PROFILE.task_types,
        min_pages_per_book=NOVEL_WIKI_PROFILE.min_pages_per_book,
        min_source_coverage=NOVEL_WIKI_PROFILE.min_source_coverage,
        min_reader_tasks=NOVEL_WIKI_PROFILE.min_reader_tasks,
        candidate_taxonomies=NOVEL_WIKI_PROFILE.candidate_taxonomies,
        chapter_exit_evidence=exit_evidence,
        closure_strict_types=NOVEL_WIKI_PROFILE.closure_strict_types,
        allowed_learning_edge_types=NOVEL_WIKI_PROFILE.allowed_learning_edge_types,
        require_target_task_match=NOVEL_WIKI_PROFILE.require_target_task_match,
    )
    gov = GovernanceConfig(external_authorized=True, budget_cap=10,
                          approver="novel-wiki-editor")
    result = evaluate_series_gate(snap, reader_profile=profile, governance=gov)

    wc = next((c for c in result.candidates if c.candidate_id == "写作技法"), None)
    assert wc is not None, f"writing-craft candidate missing: {[c.candidate_id for c in result.candidates]}"
    assert wc.eligible_page_count == 31, wc.eligible_page_count
    assert wc.closure_status == "closed", (
        f"closure_status must be 'closed' under NOVEL_WIKI_PROFILE; got {wc.closure_status!r}, "
        f"reasons={list(wc.reason_codes)}"
    )
    assert wc.decision == "proceed", (
        f"decision must be 'proceed' under NOVEL_WIKI_PROFILE; got {wc.decision!r}, "
        f"reasons={list(wc.reason_codes)}"
    )


def test_novel_wiki_profile_emits_six_real_taxonomies_not_three_books() -> None:
    """NOVEL_WIKI_PROFILE.candidate_taxonomies must contain 6 real wiki
    taxonomies and explicitly NOT contain the historical default book-a/b/c."""
    from src.kc.views.book.wiki.profiles import NOVEL_WIKI_PROFILE

    cands = set(NOVEL_WIKI_PROFILE.candidate_taxonomies)
    expected = {"写作技法", "题材体系", "心态与职业", "平台规则", "读者与市场", "案例与素材"}
    assert cands >= expected, f"missing: {expected - cands}"
    assert cands.isdisjoint({"book-a", "book-b", "book-c"}), (
        f"NOVEL_WIKI_PROFILE must not contain historical defaults: {cands & {'book-a','book-b','book-c'}}"
    )


def test_chapter_exit_evidence_derived_for_writing_craft_taxonomy() -> None:
    """derive_chapter_exit_evidence must return at least one synthesis page_id
    for the 写作技法 taxonomy."""
    from src.kc.views.book.wiki.profiles import derive_chapter_exit_evidence

    pages = _writing_craft_synthetic(n_concept=30, n_synthesis=1)
    snap = _snapshot(*pages)
    evidence = derive_chapter_exit_evidence(snap, "写作技法")
    assert "wc-s0" in evidence, evidence


def test_chapter_exit_evidence_empty_when_no_synthesis_in_candidate() -> None:
    """If the candidate has no synthesis page, derivation returns ()."""
    from src.kc.views.book.wiki.profiles import derive_chapter_exit_evidence

    pages = [_page(f"wc-c{i}") for i in range(5)]
    snap = _snapshot(*pages)
    evidence = derive_chapter_exit_evidence(snap, "写作技法")
    assert evidence == (), evidence


# ─── S0b: real wiki writing-craft has ≥1 non-namespace edge ───────────


def test_real_wiki_writing_craft_has_at_least_one_non_namespace_edge() -> None:
    """Real novel-wiki writing-craft taxonomy must contain at least one edge
    in {supports, required_by, referenced_by, supported_by, references,
    contains, is_part_of, derived_from, depends_on}. Without this, the
    entire relax strategy fails before closure_ok is computed."""
    from src.kc.views.book.wiki.scanner import scan_wiki_snapshot

    snap = scan_wiki_snapshot(__import__("pathlib").Path("knowledge/novel-wiki") / "wiki")
    wc_pages = [p for p in snap.pages if (p.primary_taxonomy or "").strip() == "写作技法"]
    assert wc_pages, "writing-craft pages missing from real wiki snapshot"

    non_namespace = {
        "supports", "required_by", "referenced_by", "supported_by",
        "references", "contains", "is_part_of", "derived_from",
        "depends_on", "analogous_to", "derives", "opposite_of",
        "causes", "caused_by", "contradicts", "related",
    }
    edges: set[tuple[str, str]] = set()
    for p in wc_pages:
        for kind, target in p.relation_targets:
            if kind in non_namespace and target in {q.page_id for q in wc_pages}:
                edges.add((p.page_id, kind, target))
    assert edges, (
        f"writing-craft has zero in-candidate non-namespace edges; "
        f"the entire relax strategy fails. wc_pages={len(wc_pages)}"
    )


# ─── S1 partial: closure_strict_types semantics ────────────────────────


def test_closure_strict_types_two_elements_relaxes_entity_requirement() -> None:
    """A 2-element closure_strict_types=('concept|foundation|orientation',
    'synthesis|application|example') must produce closure_parts with exactly
    2 booleans (not the default 3)."""
    from src.kc.views.book.wiki.profiles import NOVEL_WIKI_PROFILE

    assert len(NOVEL_WIKI_PROFILE.closure_strict_types) == 2, (
        f"NOVEL_WIKI_PROFILE.closure_strict_types must be 2 elements; got "
        f"{len(NOVEL_WIKI_PROFILE.closure_strict_types)}"
    )


def test_default_strict_closure_remains_three_elements() -> None:
    """The default ReaderProfile.closure_strict_types must remain 3
    elements to keep existing strict tests green."""
    from src.kc.views.book.wiki.partition import ReaderProfile

    default = ReaderProfile("default-test", ("learn_concept",))
    assert len(default.closure_strict_types) == 3, (
        f"default closure_strict_types must remain 3 elements; got "
        f"{len(default.closure_strict_types)}: {default.closure_strict_types}"
    )


def test_target_task_match_relaxed_allows_concept_to_concept_edge() -> None:
    """With require_target_task_match=False, a concept→concept supports edge
    must count toward has_learning_edge."""
    from src.kc.views.book.wiki.profiles import NOVEL_WIKI_PROFILE

    assert NOVEL_WIKI_PROFILE.require_target_task_match is False, (
        f"NOVEL_WIKI_PROFILE must set require_target_task_match=False; got "
        f"{NOVEL_WIKI_PROFILE.require_target_task_match}"
    )
