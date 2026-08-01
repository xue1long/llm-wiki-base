"""NDG Phase 4.2: tests for batch-level reconcile logic."""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.relations import Relation, RelationType, SYMMETRIC_RELATIONS
from src.wiki.features.batch_reconcile import (
    reconcile_batch,
    ReconcileResult,
    MergeEntry,
    ConflictEntry,
)


# ---------------------------------------------------------------------------
# Stub suppression
# ---------------------------------------------------------------------------

def test_stub_suppressed_when_real_page_exists():
    """A stub page whose slug matches a non-stub page → discarded."""
    pages = [
        WikiPage(id="ent-1", title="Real", type=PageType.ENTITY,
                  body="real content", processing_depth="concept"),
        WikiPage(id="ent-1", title="Stub", type=PageType.ENTITY,
                  body="stub body", processing_depth="stub"),
    ]
    result = reconcile_batch(pages)
    assert result.stubs_suppressed == 1
    kept_ids = {p.id for p in result.pages}
    assert len(result.pages) == 1
    # The real page survived
    real = next(p for p in result.pages if p.processing_depth != "stub")
    assert real.body == "real content"


def test_stub_kept_when_no_real_page():
    """A stub page with no non-stub counterpart → kept."""
    pages = [
        WikiPage(id="ent-1", title="Stub", type=PageType.ENTITY,
                  body="stub body", processing_depth="stub"),
    ]
    result = reconcile_batch(pages)
    assert result.stubs_suppressed == 0
    assert len(result.pages) == 1


# ---------------------------------------------------------------------------
# Same-slug same-type merge (V15)
# ---------------------------------------------------------------------------

def test_merge_same_entity_higher_grade_wins():
    """Two ENTITY pages with same slug: keep higher grade."""
    pages = [
        WikiPage(id="ent-x", title="X", type=PageType.ENTITY,
                  body="body A", grade="B",
                  relations=[Relation(target_id="other", type="related_to")]),
        WikiPage(id="ent-x", title="X2", type=PageType.ENTITY,
                  body="body B", grade="A",
                  relations=[Relation(target_id="foo", type="related_to")]),
    ]
    result = reconcile_batch(pages)
    assert len(result.pages) == 1
    assert len(result.merged) == 1
    assert result.merged[0].kept == "ent-x"
    assert result.merged[0].dropped == "ent-x"
    assert "A > B" in result.merged[0].reason or "higher grade" in result.merged[0].reason
    # Winner should have grade A and merged relations
    winner = result.pages[0]
    assert winner.grade == "A"
    target_ids = {r.target_id for r in (winner.relations or [])}
    assert "other" in target_ids  # from the loser
    assert "foo" in target_ids    # from the winner


def test_merge_same_grade_keeps_first():
    """Same slug + same type + same grade → keep first in list."""
    pages = [
        WikiPage(id="ent-x", title="First", type=PageType.ENTITY,
                  body="first", grade="B"),
        WikiPage(id="ent-x", title="Second", type=PageType.ENTITY,
                  body="second", grade="B"),
    ]
    result = reconcile_batch(pages)
    assert len(result.pages) == 1
    assert result.pages[0].body == "first"


def test_merge_does_not_duplicate_relations():
    """Loser's relations are merged without creating duplicates."""
    rel_shared = Relation(target_id="shared", type="related_to")
    pages = [
        WikiPage(id="ent-x", title="Win", type=PageType.ENTITY,
                  body="win", grade="A",
                  relations=[rel_shared]),
        WikiPage(id="ent-x", title="Lose", type=PageType.ENTITY,
                  body="lose", grade="B",
                  relations=[rel_shared,  # same as winner
                             Relation(target_id="unique", type="related_to")]),
    ]
    result = reconcile_batch(pages)
    winner = result.pages[0]
    targets = {(r.target_id, r.type) for r in (winner.relations or [])}
    assert ("shared", "related_to") in targets
    assert ("unique", "related_to") in targets
    # Count: shared appears once, unique appears once → 2 total
    assert len(winner.relations) == 2


def test_no_merge_different_types():
    """ENTITY and CONCEPT with same slug → no merge, flagged as conflict."""
    pages = [
        WikiPage(id="dup", title="E", type=PageType.ENTITY, body="a"),
        WikiPage(id="dup", title="C", type=PageType.CONCEPT, body="b"),
    ]
    result = reconcile_batch(pages)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].slug == "dup"
    assert set(result.conflicts[0].types) == {"entity", "concept"}


def test_no_merge_different_slugs():
    """Different slugs → both kept, no merge."""
    pages = [
        WikiPage(id="ent-a", title="A", type=PageType.ENTITY, body="a"),
        WikiPage(id="ent-b", title="B", type=PageType.ENTITY, body="b"),
    ]
    result = reconcile_batch(pages)
    assert len(result.pages) == 2
    assert len(result.merged) == 0
    assert len(result.conflicts) == 0


# ---------------------------------------------------------------------------
# Integration: stub + merge in same batch
# ---------------------------------------------------------------------------

def test_reconcile_stub_and_merge_together():
    """Batch has a stub (suppressed), a duplicate entity pair (merged),
    and a cross-type conflict."""
    pages = [
        # stub → suppressed by real page below
        WikiPage(id="ent-1", title="Stub", type=PageType.ENTITY,
                  body="stub", processing_depth="stub"),
        # real page
        WikiPage(id="ent-1", title="Real", type=PageType.ENTITY,
                  body="real", processing_depth="concept", grade="A"),
        # duplicate entity pair → merged
        WikiPage(id="ent-2", title="Better", type=PageType.ENTITY,
                  body="better", grade="A"),
        WikiPage(id="ent-2", title="Worse", type=PageType.ENTITY,
                  body="worse", grade="C"),
        # cross-type conflict
        WikiPage(id="shared", title="Entity", type=PageType.ENTITY, body="e"),
        WikiPage(id="shared", title="Concept", type=PageType.CONCEPT, body="c"),
    ]
    result = reconcile_batch(pages)

    assert result.stubs_suppressed == 1
    assert len(result.merged) == 1
    assert len(result.conflicts) == 1

    # After reconcile: 6 pages → stub gone (1), ent-2 merged (1) → 4 pages
    assert len(result.pages) == 4


# ---------------------------------------------------------------------------
# Extra pages passthrough
# ---------------------------------------------------------------------------

def test_extra_pages_kept_separate_in_extras():
    """Non-colliding extra pages are returned in result.extras, never mixed
    into result.pages."""
    extra = [
        WikiPage(id="extra-1", title="Extra", type=PageType.ENTITY,
                  body="existing"),
    ]
    pages = [
        WikiPage(id="new-1", title="New", type=PageType.ENTITY, body="new"),
    ]
    result = reconcile_batch(pages, extra_pages=extra)
    assert [p.id for p in result.pages] == ["new-1"]
    assert [p.id for p in result.extras] == ["extra-1"]


# ---------------------------------------------------------------------------
# Cross-type conflict: wiki-known slug wins (NDG Phase 6 resolution)
# ---------------------------------------------------------------------------

def _make_wiki_with(root, entries):
    """Write a minimal wiki/index.md with the given (slug, type) entries and
    return the WikiPaths object."""
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.ensure import ensure_knowledge_base
    paths = ensure_knowledge_base(root)
    idx_lines = ["# Wiki Index\n"]
    for slug, ptype in entries:
        idx_lines.append(f"- **{slug}** ({ptype.value}) — {slug}\n")
    paths.llm_wiki_index.write_text("".join(idx_lines), encoding="utf-8")
    return paths


def test_cross_type_conflict_resolved_by_wiki_type(tmp_path):
    """When the wiki already has a slug (e.g. as concept), the batch's
    same-slug page of the *other* type (entity) is dropped — no conflict."""
    paths = _make_wiki_with(tmp_path, [("三清", PageType.CONCEPT)])

    pages = [
        WikiPage(id="三清", title="三清", type=PageType.ENTITY, body="entity ver"),
        WikiPage(id="三清", title="三清", type=PageType.CONCEPT, body="concept ver"),
    ]
    result = reconcile_batch(pages, paths=paths)

    assert result.conflicts == [], "wiki-known slug must not be a conflict"
    kept = [p for p in result.pages if p.id == "三清"]
    assert len(kept) == 1, "only the wiki-typed page survives"
    assert kept[0].type == PageType.CONCEPT


def test_cross_type_conflict_still_flag_when_wiki_unknown(tmp_path):
    """When the wiki has no entry for the slug, entity/concept collision is
    still reported as a conflict (cannot pick a side)."""
    paths = _make_wiki_with(tmp_path, [])  # empty wiki

    pages = [
        WikiPage(id="新实体", title="新实体", type=PageType.ENTITY, body="e"),
        WikiPage(id="新实体", title="新实体", type=PageType.CONCEPT, body="c"),
    ]
    result = reconcile_batch(pages, paths=paths)

    assert len(result.conflicts) == 1
    assert result.conflicts[0].slug == "新实体"
    assert set(result.conflicts[0].types) == {"entity", "concept"}


def test_cross_type_drop_folds_relations_into_survivor(tmp_path):
    """Dropped cross-type pages' relations are folded into the surviving
    wiki-typed page so no information is lost."""
    paths = _make_wiki_with(tmp_path, [("三清", PageType.CONCEPT)])

    pages = [
        WikiPage(id="三清", title="三清", type=PageType.ENTITY, body="e",
                 sources=["raw/sources/foo.md"],
                 relations=[Relation(target_id="某道场", type="located_at")]),
        WikiPage(id="三清", title="三清", type=PageType.CONCEPT, body="c",
                 sources=["raw/sources/bar.md"]),
    ]
    result = reconcile_batch(pages, paths=paths)

    assert result.conflicts == []
    survivor = next(p for p in result.pages if p.id == "三清")
    assert survivor.type == PageType.CONCEPT
    # Dropped entity page's relations + sources folded in.
    rel_targets = {r.target_id for r in (survivor.relations or [])}
    assert "某道场" in rel_targets, "dropped page's relations must be folded"
    assert "raw/sources/foo.md" in (survivor.sources or [])


def test_cross_type_conflict_wiki_type_matches_batch_keeps_both_same_type(tmp_path):
    """If the wiki knows the slug as concept and the batch only has concept
    pages (no entity), nothing is dropped — the two same-type pages are
    merged (V15) rather than flagged as a cross-type conflict."""
    paths = _make_wiki_with(tmp_path, [("六御", PageType.CONCEPT)])

    pages = [
        WikiPage(id="六御", title="六御", type=PageType.CONCEPT, body="c1"),
        WikiPage(id="六御", title="六御", type=PageType.CONCEPT, body="c2"),
    ]
    result = reconcile_batch(pages, paths=paths)

    assert result.conflicts == [], "same-type pages are not a cross-type conflict"
    kept = [p for p in result.pages if p.id == "六御"]
    assert len(kept) == 1, "same-type duplicate pages are merged to one"
    assert kept[0].type == PageType.CONCEPT


# ---------------------------------------------------------------------------
# Extra-page management (R1-2): fold by id, adjudicate collisions by grade
# ---------------------------------------------------------------------------

def test_extra_duplicates_folded_relations_union():
    """Two extras with the same id → one survives; relations are unioned (B2)."""
    pages = [
        WikiPage(id="batch-1", title="Batch", type=PageType.ENTITY, body="b"),
    ]
    extras = [
        WikiPage(id="extra-x", title="X", type=PageType.ENTITY, body="same body",
                 relations=[Relation(target_id="a", type="references")]),
        WikiPage(id="extra-x", title="X", type=PageType.ENTITY, body="same body",
                 relations=[Relation(target_id="b", type="references")]),
    ]
    result = reconcile_batch(pages, extra_pages=extras)
    assert len(result.extras) == 1
    assert result.extras[0].id == "extra-x"
    targets = {(r.target_id, r.type) for r in (result.extras[0].relations or [])}
    assert ("a", "references") in targets
    assert ("b", "references") in targets


def test_extra_collision_batch_equal_higher_grade_folds_extra():
    """Extra collides with a batch page of equal-or-higher grade → the extra's
    relations fold into the batch page and the extra is dropped (A3)."""
    pages = [
        WikiPage(id="ent-1", title="Batch", type=PageType.ENTITY,
                 body="batch body", grade="A",
                 relations=[Relation(target_id="own", type="references")]),
    ]
    extras = [
        WikiPage(id="ent-1", title="Existing", type=PageType.ENTITY,
                 body="existing body", grade="B",
                 relations=[Relation(target_id="ext", type="references")]),
    ]
    result = reconcile_batch(pages, extra_pages=extras)
    assert [p.id for p in result.pages] == ["ent-1"]
    assert result.pages[0].body == "batch body"   # batch page kept
    assert result.extras == []                    # extra folded, not kept
    targets = {(r.target_id, r.type) for r in (result.pages[0].relations or [])}
    assert ("own", "references") in targets
    assert ("ext", "references") in targets       # extra's relations folded in
    assert len(result.merged) == 1
    assert result.merged[0].kept == "ent-1"
    assert result.merged[0].dropped == "ent-1"
    assert "extra folded" in result.merged[0].reason


def test_extra_collision_extra_higher_grade_wins():
    """Extra collides with a batch page of lower grade → the extra survives
    (goes to result.extras) and the batch page is dropped (F3)."""
    pages = [
        WikiPage(id="ent-1", title="Batch", type=PageType.ENTITY,
                 body="batch body", grade="B",
                 relations=[Relation(target_id="br", type="references")]),
    ]
    extras = [
        WikiPage(id="ent-1", title="Existing", type=PageType.ENTITY,
                 body="existing body", grade="A",
                 relations=[Relation(target_id="er", type="references")]),
    ]
    result = reconcile_batch(pages, extra_pages=extras)
    assert result.pages == [], "lower-grade batch page must be dropped"
    assert len(result.extras) == 1
    assert result.extras[0].id == "ent-1"
    assert result.extras[0].body == "existing body"
    assert len(result.merged) == 1
    assert result.merged[0].kept == "ent-1"
    assert result.merged[0].dropped == "ent-1"
    assert "higher grade" in result.merged[0].reason


# ---------------------------------------------------------------------------
# Batch-level reverse-edge recompute (R2-1, B1)
# ---------------------------------------------------------------------------

def test_reverse_relations_created_within_batch():
    """Batch page A references batch page B → B gains referenced_by → A (B1)."""
    pages = [
        WikiPage(id="A", title="A", type=PageType.ENTITY, body="a",
                 relations=[Relation(target_id="B", type="references")]),
        WikiPage(id="B", title="B", type=PageType.ENTITY, body="b"),
    ]
    result = reconcile_batch(pages)
    by_id = {p.id: p for p in result.pages}
    b_edges = {(r.type, r.target_id) for r in (by_id["B"].relations or [])}
    assert ("referenced_by", "A") in b_edges


def test_reverse_relations_skip_symmetric():
    """Symmetric relations (contradicts) do not produce an inverse edge."""
    pages = [
        WikiPage(id="A", title="A", type=PageType.ENTITY, body="a",
                 relations=[Relation(target_id="B", type="contradicts")]),
        WikiPage(id="B", title="B", type=PageType.ENTITY, body="b"),
    ]
    result = reconcile_batch(pages)
    by_id = {p.id: p for p in result.pages}
    assert (by_id["B"].relations or []) == []


def test_reverse_relations_to_extra_not_duplicated():
    """Batch page A references existing page X (passed as extra); if X already
    holds the reverse edge it is not added a second time."""
    pages = [
        WikiPage(id="A", title="A", type=PageType.ENTITY, body="a",
                 relations=[Relation(target_id="X", type="references")]),
    ]
    extras = [
        WikiPage(id="X", title="X", type=PageType.ENTITY, body="x",
                 relations=[Relation(target_id="A", type="referenced_by")]),
    ]
    result = reconcile_batch(pages, extra_pages=extras)
    by_id = {p.id: p for p in result.pages}
    by_id.update({p.id: p for p in result.extras})
    x_edges = [(r.type, r.target_id) for r in (by_id["X"].relations or [])]
    assert x_edges.count(("referenced_by", "A")) == 1


def test_relation_inverse_defined_for_all_non_symmetric_types():
    """Every non-symmetric RelationType has a defined inverse (safety net for
    the batch reverse-edge recompute)."""
    for rt in RelationType:
        if rt.value in SYMMETRIC_RELATIONS:
            continue
        rel = Relation(target_id="other", type=rt.value)
        assert rel.inverse() is not None, f"{rt.value} should have an inverse"
