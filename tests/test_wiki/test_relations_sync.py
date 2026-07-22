"""Tests for RelationSync (bidirectional) + RelationQuery (list/backlinks/neighbors/path)."""
import pytest

from src.wiki.ensure import ensure_knowledge_base
from src.wiki.page_writer import page_path_for, read_page, write_page
from src.wiki.paths import WikiPaths
from src.wiki.relations import (
    Relation, RelationSync, RelationQuery,
)
from src.wiki.types import PageType, WikiPage


def _make_page(paths: WikiPaths, slug: str, type_: PageType, body: str = "x") -> None:
    """Helper: create a wiki page on disk."""
    page = WikiPage(
        id=slug, title=slug, type=type_, created_at=1000, updated_at=2000, body=body,
    )
    write_page(paths, page)


def test_sync_adds_inverse(tmp_path):
    """sync_page writes relations to source page and adds inverse to target page."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "src", PageType.SOURCE)
    _make_page(p, "concept", PageType.CONCEPT)

    relations = [Relation(target_id="concept", type="references", weight=0.7, context="see also")]
    report = RelationSync.sync_page(p, "src", relations)

    # Source page now has the relation
    src_page = read_page(page_path_for(p, PageType.SOURCE, "src"))
    assert len(src_page.relations) == 1
    assert src_page.relations[0].target_id == "concept"
    assert src_page.relations[0].type == "references"

    # Target page received the inverse
    concept_page = read_page(page_path_for(p, PageType.CONCEPT, "concept"))
    assert len(concept_page.relations) == 1
    assert concept_page.relations[0].target_id == "src"
    assert concept_page.relations[0].type == "referenced_by"

    # Report claims both pages were updated
    assert report.page_id == "src"
    assert len(report.added) == 1
    assert report.added[0].target_id == "concept"


def test_sync_idempotent(tmp_path):
    """Calling sync_page twice with same relations doesn't duplicate inverses."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "src", PageType.SOURCE)
    _make_page(p, "concept", PageType.CONCEPT)

    relations = [Relation(target_id="concept", type="references", weight=0.7)]

    # First sync
    RelationSync.sync_page(p, "src", relations)
    # Second sync (same relations)
    RelationSync.sync_page(p, "src", relations)

    # Target page should have only one inverse (no duplicates)
    concept_page = read_page(page_path_for(p, PageType.CONCEPT, "concept"))
    inverses = [r for r in concept_page.relations if r.target_id == "src"]
    assert len(inverses) == 1
    assert inverses[0].type == "referenced_by"


def test_find_backlinks(tmp_path):
    """find_backlinks returns relations across all wiki subdirs targeting page_id."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Create target page in entities
    _make_page(p, "target", PageType.ENTITY)
    # Create source pages referencing it from different subdirs
    _make_page(
        p, "source_a", PageType.SOURCE,
        body="placeholder",
    )
    _make_page(p, "source_b", PageType.ENTITY)
    _make_page(p, "source_c", PageType.CONCEPT)

    # Manually add relations pointing at "target"
    sa = read_page(page_path_for(p, PageType.SOURCE, "source_a"))
    sa.relations.append(Relation(target_id="target", type="references", weight=0.5))
    write_page(p, sa)

    sb = read_page(page_path_for(p, PageType.ENTITY, "source_b"))
    sb.relations.append(Relation(target_id="target", type="supports", weight=0.8))
    write_page(p, sb)

    sc = read_page(page_path_for(p, PageType.CONCEPT, "source_c"))
    sc.relations.append(Relation(target_id="target", type="derived_from", weight=0.3))
    write_page(p, sc)

    backlinks = RelationQuery.find_backlinks(p, "target")
    sources = sorted(r.target_id for r in backlinks)
    assert sources == ["source_a", "source_b", "source_c"]
    types = sorted(r.type for r in backlinks)
    assert types == ["derived_from", "references", "supports"]


def test_find_neighbors(tmp_path):
    """find_neighbors BFS traverses relations up to depth hops."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "a", PageType.SOURCE)
    _make_page(p, "b", PageType.SOURCE)
    _make_page(p, "c", PageType.SOURCE)
    _make_page(p, "d", PageType.SOURCE)

    # a → b (references, weight 0.5)
    # b → c (supports, weight 0.4)
    # a → d (causes, weight 0.7)
    page_a = read_page(page_path_for(p, PageType.SOURCE, "a"))
    page_a.relations.append(Relation(target_id="b", type="references", weight=0.5))
    page_a.relations.append(Relation(target_id="d", type="causes", weight=0.7))
    write_page(p, page_a)

    page_b = read_page(page_path_for(p, PageType.SOURCE, "b"))
    page_b.relations.append(Relation(target_id="c", type="supports", weight=0.4))
    write_page(p, page_b)

    # Depth 1: only b and d
    neighbors_1 = RelationQuery.find_neighbors(p, "a", depth=1)
    ids_1 = sorted(n[0] for n in neighbors_1)
    assert ids_1 == ["b", "d"]

    # Depth 2: also c (b → c)
    neighbors_2 = RelationQuery.find_neighbors(p, "a", depth=2)
    ids_2 = sorted(n[0] for n in neighbors_2)
    assert ids_2 == ["b", "c", "d"]

    # Verify cumulative weight: a → b = 0.5, a → b → c = 0.5 * 0.4 = 0.2
    by_id = {n[0]: n for n in neighbors_2}
    assert by_id["b"][1] == "references"
    assert abs(by_id["b"][2] - 0.5) < 0.01
    assert by_id["c"][1] == "supports"
    assert abs(by_id["c"][2] - 0.2) < 0.01
    assert by_id["d"][1] == "causes"
    assert abs(by_id["d"][2] - 0.7) < 0.01


def test_find_path(tmp_path):
    """find_path returns shortest BFS path between two pages."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "a", PageType.SOURCE)
    _make_page(p, "b", PageType.SOURCE)
    _make_page(p, "c", PageType.SOURCE)
    _make_page(p, "d", PageType.SOURCE)

    # a → b, b → c, c → d
    page_a = read_page(page_path_for(p, PageType.SOURCE, "a"))
    page_a.relations.append(Relation(target_id="b", type="references"))
    write_page(p, page_a)

    page_b = read_page(page_path_for(p, PageType.SOURCE, "b"))
    page_b.relations.append(Relation(target_id="c", type="supports"))
    write_page(p, page_b)

    page_c = read_page(page_path_for(p, PageType.SOURCE, "c"))
    page_c.relations.append(Relation(target_id="d", type="causes"))
    write_page(p, page_c)

    # Same source/target → empty
    assert RelationQuery.find_path(p, "a", "a") == []

    # Path a → d via b, c
    path = RelationQuery.find_path(p, "a", "d")
    assert path == [
        ("a", "b", "references"),
        ("b", "c", "supports"),
        ("c", "d", "causes"),
    ]

    # No path exists (d has no outgoing relations, e doesn't exist)
    assert RelationQuery.find_path(p, "d", "e") == []  # noqa


def test_list_relations(tmp_path):
    """list_relations returns the page's own relations."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "src", PageType.SOURCE)

    page = read_page(page_path_for(p, PageType.SOURCE, "src"))
    page.relations.append(Relation(target_id="x", type="references", weight=0.5))
    page.relations.append(Relation(target_id="y", type="supports", weight=0.9))
    write_page(p, page)

    rels = RelationQuery.list_relations(p, "src")
    assert len(rels) == 2
    targets = sorted(r.target_id for r in rels)
    assert targets == ["x", "y"]


def test_sync_skips_symmetric_inverse(tmp_path):
    """Symmetric relations (contradicts/analogous_to/opposite_of) don't duplicate inverse."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    _make_page(p, "src", PageType.SOURCE)
    _make_page(p, "concept", PageType.CONCEPT)

    relations = [Relation(target_id="concept", type="contradicts", weight=0.8)]
    report = RelationSync.sync_page(p, "src", relations)

    # Source page has the relation
    src_page = read_page(page_path_for(p, PageType.SOURCE, "src"))
    assert len(src_page.relations) == 1
    assert src_page.relations[0].type == "contradicts"

    # Target page does NOT get a duplicate inverse
    concept_page = read_page(page_path_for(p, PageType.CONCEPT, "concept"))
    assert concept_page.relations == []
