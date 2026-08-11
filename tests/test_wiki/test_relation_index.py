"""Tests for relation_index (flat-file adjacency index)."""
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import page_path_for, read_page, write_page
from src.wiki.core.paths import WikiPaths
from src.wiki.features.relations import Relation, RelationSync, RelationQuery
from src.wiki.features.relation_index import (
    write_outgoing,
    write_backlinks_for_source,
    read_outgoing,
    read_backlinks,
    remove_source_from_index,
    rebuild_index,
)


def _make_page(paths: WikiPaths, slug: str, type_: PageType, body: str = "x") -> None:
    page = WikiPage(
        id=slug, title=slug, type=type_, created_at=1000, updated_at=2000, body=body,
    )
    write_page(paths, page)


def test_write_and_read_outgoing(tmp_path):
    """Write outgoing relations then read them back."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    rels = [
        {"target": "b", "type": "references", "weight": 0.5, "context": ""},
        {"target": "c", "type": "supports", "weight": 0.8, "context": "note"},
    ]
    write_outgoing(paths, "a", rels)
    result = read_outgoing(paths, "a")
    assert len(result) == 2
    assert result[0]["target"] == "b"
    assert result[1]["target"] == "c"


def test_write_and_read_backlinks(tmp_path):
    """Backlinks index tracks sources that point to a target."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_backlinks_for_source(paths, "a", [
        {"target": "t", "type": "references", "weight": 0.5, "context": ""},
    ])
    write_backlinks_for_source(paths, "b", [
        {"target": "t", "type": "supports", "weight": 0.8, "context": ""},
    ])
    bl = read_backlinks(paths, "t")
    assert len(bl) == 2
    sources = sorted(b["source"] for b in bl)
    assert sources == ["a", "b"]


def test_backlinks_idempotent_upsert(tmp_path):
    """Writing the same source→target twice updates, not duplicates."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_backlinks_for_source(paths, "a", [
        {"target": "t", "type": "ref", "weight": 0.5, "context": ""},
    ])
    write_backlinks_for_source(paths, "a", [
        {"target": "t", "type": "ref", "weight": 0.9, "context": "updated"},
    ])
    bl = read_backlinks(paths, "t")
    assert len(bl) == 1
    assert bl[0]["weight"] == 0.9
    assert bl[0]["context"] == "updated"


def test_remove_source_from_index(tmp_path):
    """Removing a source clears its outgoing + all backlink references."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_outgoing(paths, "a", [
        {"target": "b", "type": "references", "weight": 1.0, "context": ""},
    ])
    write_backlinks_for_source(paths, "a", [
        {"target": "b", "type": "references", "weight": 1.0, "context": ""},
    ])
    remove_source_from_index(paths, "a")
    assert read_outgoing(paths, "a") == []
    assert read_backlinks(paths, "b") == []


def test_rebuild_index(tmp_path):
    """Full rebuild from wiki pages restores index consistency."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    _make_page(paths, "src", PageType.SOURCE)
    _make_page(paths, "tgt", PageType.ENTITY)

    page = read_page(page_path_for(paths, PageType.SOURCE, "src"))
    page.relations.append(Relation(target_id="tgt", type="references", weight=0.7))
    write_page(paths, page)

    count = rebuild_index(paths)
    assert count == 1
    assert len(read_outgoing(paths, "src")) == 1
    assert len(read_backlinks(paths, "tgt")) == 1


def test_find_backlinks_uses_index(tmp_path):
    """After sync_page, find_backlinks reads from index (not full scan)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    _make_page(paths, "src", PageType.SOURCE)
    _make_page(paths, "tgt", PageType.ENTITY)

    RelationSync.sync_page(paths, "src", [
        Relation(target_id="tgt", type="references", weight=0.7),
    ])
    backlinks = RelationQuery.find_backlinks(paths, "tgt")
    assert len(backlinks) == 1
    assert backlinks[0].target_id == "src"
    assert backlinks[0].type == "references"


def test_find_neighbors_uses_index(tmp_path):
    """find_neighbors reads outgoing from index (not full page scan)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    _make_page(paths, "a", PageType.SOURCE)
    _make_page(paths, "b", PageType.SOURCE)
    _make_page(paths, "c", PageType.SOURCE)

    RelationSync.sync_page(paths, "a", [
        Relation(target_id="b", type="references", weight=0.5),
    ])
    RelationSync.sync_page(paths, "b", [
        Relation(target_id="c", type="supports", weight=0.4),
    ])

    neighbors = RelationQuery.find_neighbors(paths, "a", depth=2)
    ids = sorted(n[0] for n in neighbors)
    assert ids == ["b", "c"]
