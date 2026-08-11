"""Tests for scripts/batch_build.py phase_archive stub-skip (C8).

Placeholder pages (frontmatter ``processing_depth: stub``) must be excluded
from the notes scan so they never get embedded into the vector store.
"""
import argparse
import asyncio

import scripts.batch_build as batch_build
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def test_phase_archive_skips_stub_pages(tmp_path, monkeypatch):
    """Placeholder pages (frontmatter processing_depth: stub) must not be
    passed to the archive coroutine — only real notes get embedded."""
    paths = ensure_knowledge_base(tmp_path)
    write_page(paths, WikiPage(
        id="占位", title="占位", type=PageType.CONCEPT,
        body="占位条目，此条目仅作占位。", grade="C", processing_depth="stub",
        sources=["raw/sources/test.md"],
    ))
    write_page(paths, WikiPage(
        id="真实", title="真实", type=PageType.ENTITY,
        body="这是一篇真实的笔记内容。", processing_depth="concept",
        sources=["raw/sources/test.md"],
    ))
    stub_path = paths.wiki_concepts / "占位.md"
    real_path = paths.wiki_entities / "真实.md"

    archived: list[str] = []

    async def _fake_archive(task_id, note_path, paths):
        archived.append(str(note_path))
        return "ok"

    async def _fake_init_embedding():
        class _Provider:
            async def close(self):
                pass
        return _Provider()

    monkeypatch.setattr("src.vector.store.init_vector_store_for_paths", lambda _paths: None)
    monkeypatch.setattr("src.pipeline.librarian.archive", _fake_archive)
    monkeypatch.setattr(batch_build, "init_embedding", _fake_init_embedding)

    args = argparse.Namespace(dry_run=False, force=True)
    state = {"ingested": {}, "archived": {}, "failed": {}}

    asyncio.run(batch_build.phase_archive(tmp_path, state, args))

    assert str(stub_path) not in archived, "stub page must not be archived"
    assert str(real_path) in archived, "real page must still be archived"
