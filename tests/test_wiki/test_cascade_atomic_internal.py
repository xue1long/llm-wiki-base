"""Tests for I-pipeline-2 (partial fix in T8): cascade_delete opens its own
atomic_pipeline_op internally; callers no longer need to wrap it.

Before T8 the function relied on the caller wrapping it in atomic_pipeline_op
(which was inconsistent and easy to forget). T8 self-wraps it so the
delete-cascade always commits as one batch.
"""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.cascade_delete import cascade_delete
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index
from src.lib.write_hooks import flush_pending_writes


def test_cascade_delete_self_wraps_in_atomic_context(tmp_path, monkeypatch):
    """Calling cascade_delete WITHOUT an outer AtomicContext must still
    defer deletions safely — when write_page fails mid-flight, no
    deletions leak to disk."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf", "raw/sources/y.pdf"], body="links"))

    def fail_write(*args, **kwargs):
        raise RuntimeError("mid-operation")

    monkeypatch.setattr("src.wiki.features.cascade_delete.write_page", fail_write)

    # No `with atomic_pipeline_op(p):` wrapper — cascade_delete opens its own.
    with pytest.raises(RuntimeError):
        cascade_delete(p, "src-1")

    # Source and entity files must still exist on disk; nothing leaked.
    assert (p.wiki_sources / "src-1.md").exists()
    assert (p.wiki_entities / "ent-a.md").exists()
    flush_pending_writes()


def test_cascade_delete_commits_atomically_without_caller_wrapper(tmp_path):
    """Happy path: cascade_delete called plainly (no caller AtomicContext)
    still commits all writes atomically."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links"))
    write_page(p, WikiPage(id="ent-b", title="B", type=PageType.ENTITY, sources=["raw/sources/y.pdf"], body="also links"))
    append_to_index(p, [("src-1", PageType.SOURCE, "Source"), ("ent-a", PageType.ENTITY, "A"), ("ent-b", PageType.ENTITY, "B")])

    # Plain call, no outer atomic_pipeline_op.
    result = cascade_delete(p, "src-1")

    assert not (p.wiki_sources / "src-1.md").exists()
    assert not (p.wiki_entities / "ent-a.md").exists()
    assert (p.wiki_entities / "ent-b.md").exists()
    assert "src-1" not in p.llm_wiki_index.read_text(encoding="utf-8")
    assert result["deleted_source"] is True
    assert "ent-a" in result["deleted_pages"]


def test_cascade_delete_idempotent_under_nested_atomic_context(tmp_path):
    """If the caller ALSO wraps in atomic_pipeline_op, the nested context
    is a no-op (cascade_delete's own inner context is the outer one that
    actually flushes) — no duplicate flushes, no broken state."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links"))

    from src.wiki.storage.atomic_ctx_helpers import atomic_pipeline_op
    with atomic_pipeline_op(p):
        result = cascade_delete(p, "src-1")

    assert result["deleted_source"] is True
    assert not (p.wiki_sources / "src-1.md").exists()
    assert not (p.wiki_entities / "ent-a.md").exists()