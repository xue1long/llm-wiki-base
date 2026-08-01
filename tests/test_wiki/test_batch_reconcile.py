"""NDG Phase 4.2: tests for batch-level reconcile logic."""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.relations import Relation
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

def test_extra_pages_included_in_output():
    """Extra pages are included in the reconciled output (not subject to merge)."""
    extra = [
        WikiPage(id="extra-1", title="Extra", type=PageType.ENTITY,
                  body="existing"),
    ]
    pages = [
        WikiPage(id="new-1", title="New", type=PageType.ENTITY, body="new"),
    ]
    result = reconcile_batch(pages, extra_pages=extra)
    assert len(result.pages) == 2
    assert any(p.id == "extra-1" for p in result.pages)
    assert any(p.id == "new-1" for p in result.pages)
