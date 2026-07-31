"""Cross-device self-heal: librarian stores PROJECT-RELATIVE paths and merges
against relative existing_path values.

Before the fix, VectorChunk.path and the ``**合并来源**`` provenance were
absolute paths, which broke on the next device. After the fix both are
root-relative (``wiki/sources/...``) and _merge_duplicates resolves stored
relative paths against the current root.
"""
import pytest

from src.wiki.core.paths import WikiPaths
from src.pipeline import librarian


class _FakeResult:
    def __init__(self, path: str, score: float = 0.99):
        self.path = path
        self.score = score


def _stub_provider(embedding=(0.1,)):
    class _E:
        def __init__(self, embedding):
            self.embedding = embedding

    class _P:
        async def embed(self, texts):
            return [_E(list(embedding) * 1536) for _ in texts]
    return _P()


@pytest.mark.asyncio
async def test_archive_merges_relative_existing_path(tmp_path, monkeypatch):
    """A stored RELATIVE existing_path resolves against root and merges, with
    the provenance written as a relative path."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    existing = paths.wiki_sources / "good.md"
    existing.write_text("original", encoding="utf-8")
    note = paths.wiki_sources / "new.md"
    note.write_text("# New\n\nContent here.", encoding="utf-8")

    monkeypatch.setattr(librarian, "get_embedding_provider", lambda: _stub_provider())
    monkeypatch.setattr(
        librarian,
        "vector_search_chunks",
        lambda emb, top_k, **kw: [_FakeResult(path="wiki/sources/good.md", score=0.99)],
    )

    payload = await librarian.archive(task_id="t-merge", note_path=str(note), paths=paths)

    assert type(payload).__name__ == "LibrarianMergedPayload"
    updated = existing.read_text(encoding="utf-8")
    assert "**合并来源**: wiki/sources/new.md" in updated
    assert "**合并时间**" in updated


@pytest.mark.asyncio
async def test_archive_stores_relative_chunk_paths(tmp_path, monkeypatch):
    """Normal archive (no similar hit) upserts VectorChunks whose path is
    root-relative."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    note = paths.wiki_sources / "note.md"
    note.write_text("# Heading\n\nSome body content.", encoding="utf-8")

    monkeypatch.setattr(librarian, "get_embedding_provider", lambda: _stub_provider())
    monkeypatch.setattr(librarian, "vector_search_chunks", lambda emb, top_k, **kw: [])

    captured = []
    monkeypatch.setattr(librarian, "vector_upsert_chunks", lambda chunks: captured.extend(chunks))

    payload = await librarian.archive(task_id="t-plain", note_path=str(note), paths=paths)
    assert payload.chunk_count > 0
    assert captured
    assert all(c.path == "wiki/sources/note.md" for c in captured)
