# tests/test_wiki/test_cascade_delete.py
from src.wiki.types import PageType, WikiPage
from src.wiki.cascade_delete import cascade_delete
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page
from src.wiki.indexer import append_to_index
from src.wiki.atomic_ctx_helpers import atomic_pipeline_op
import pytest


def test_cascade_delete_removes_source_and_updates_relations(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    # Source page + 2 entity pages that reference it
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE,
                          sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY,
                          sources=["raw/sources/x.pdf"], body="links to source"))
    write_page(p, WikiPage(id="ent-b", title="B", type=PageType.ENTITY,
                          sources=["raw/sources/y.pdf"], body="also links to source"))
    append_to_index(p, [("src-1", PageType.SOURCE, "Source"),
                        ("ent-a", PageType.ENTITY, "A"),
                        ("ent-b", PageType.ENTITY, "B")])

    # Run cascade delete for source src-1
    with atomic_pipeline_op(p):
        result = cascade_delete(p, "src-1")

    # Source page deleted
    assert not (p.wiki_sources / "src-1.md").exists()
    # Index updated
    content = p.llm_wiki_index.read_text(encoding="utf-8")
    assert "src-1" not in content
    # ent-a still exists (now has empty sources → deleted)
    assert not (p.wiki_entities / "ent-a.md").exists()
    # ent-b still exists (unaffected by src-1)
    assert (p.wiki_entities / "ent-b.md").exists()
    # Return value
    assert result["deleted_source"] is True
    assert "ent-a" in result["deleted_pages"]


def test_cascade_delete_missing_source(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    with pytest.raises(FileNotFoundError):
        cascade_delete(p, "nonexistent")