import pytest
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.cascade_delete import cascade_delete
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index
from src.wiki.storage.atomic_ctx_helpers import atomic_pipeline_op
from src.lib.write_hooks import flush_pending_writes


def test_cascade_delete_defers_deletions_on_failure(tmp_path, monkeypatch):
    ensure_knowledge_base(tmp_path); p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf", "raw/sources/y.pdf"], body="links"))
    def fail_write(*args, **kwargs): raise RuntimeError("mid-operation")
    monkeypatch.setattr("src.wiki.features.cascade_delete.write_page", fail_write)
    with pytest.raises(RuntimeError):
        with atomic_pipeline_op(p): cascade_delete(p, "src-1")
    assert (p.wiki_sources / "src-1.md").exists()
    assert (p.wiki_entities / "ent-a.md").exists()
    flush_pending_writes()


def test_cascade_delete_removes_source_and_updates_relations(tmp_path):
    ensure_knowledge_base(tmp_path); p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links to source"))
    write_page(p, WikiPage(id="ent-b", title="B", type=PageType.ENTITY, sources=["raw/sources/y.pdf"], body="also links to source"))
    append_to_index(p, [("src-1", PageType.SOURCE, "Source"), ("ent-a", PageType.ENTITY, "A"), ("ent-b", PageType.ENTITY, "B")])
    with atomic_pipeline_op(p): result = cascade_delete(p, "src-1")
    assert not (p.wiki_sources / "src-1.md").exists()
    assert "src-1" not in p.llm_wiki_index.read_text(encoding="utf-8")
    assert not (p.wiki_entities / "ent-a.md").exists()
    assert (p.wiki_entities / "ent-b.md").exists()
    assert result["deleted_source"] is True
    assert "ent-a" in result["deleted_pages"]


def test_cascade_delete_missing_source(tmp_path):
    ensure_knowledge_base(tmp_path); p = WikiPaths(tmp_path)
    with pytest.raises(FileNotFoundError): cascade_delete(p, "nonexistent")
