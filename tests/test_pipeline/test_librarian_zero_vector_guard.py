"""Audit M2 regression: librarian.archive() must refuse to write zero vectors
when the embedding provider returns no embeddings.

Previously the code silently wrote ``[[0.0] * 1536]`` placeholders to the
vector store, which poisons the index (zero-vector similarity is meaningless
and pulls unrelated chunks together). The fix raises a RuntimeError so the
caller surfaces a clear error.
"""
import pytest

from src.wiki.core.paths import WikiPaths
from src.pipeline import librarian


@pytest.mark.asyncio
async def test_archive_raises_when_no_embeddings_produced(tmp_path, monkeypatch):
    """If the embed call yields no embeddings, archive() must raise."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.knowledge_dir.mkdir(parents=True, exist_ok=True)

    note = tmp_path / "note.md"
    note.write_text("# Heading\n\nSome body content here.", encoding="utf-8")

    # Provider returns an empty list — simulate a missing or failed embedding
    # backend. ``archive`` must not silently proceed with zero vectors.
    class _EmptyProvider:
        async def embed(self, texts):
            return []

    monkeypatch.setattr(librarian, "get_embedding_provider", lambda: _EmptyProvider())
    monkeypatch.setattr(librarian, "vector_search_chunks", lambda emb, top_k, **kw: [])

    # Spy: if the code attempts to upsert zero vectors, fail loudly.
    def _fail(_chunks):
        pytest.fail(
            "vector_upsert_chunks must NOT be called when no embeddings are produced"
        )

    monkeypatch.setattr(librarian, "vector_upsert_chunks", _fail)

    with pytest.raises(RuntimeError, match="No embeddings produced"):
        await librarian.archive(
            task_id="t-empty",
            note_path=str(note),
            paths=paths,
        )


@pytest.mark.asyncio
async def test_archive_proceeds_normally_when_embeddings_present(tmp_path, monkeypatch):
    """When the embed call returns embeddings, archive() proceeds normally."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.knowledge_dir.mkdir(parents=True, exist_ok=True)

    note = tmp_path / "note.md"
    note.write_text("# Heading\n\nSome body content here.", encoding="utf-8")

    class _StubProvider:
        async def embed(self, texts):
            class _E:
                def __init__(self, embedding):
                    self.embedding = embedding
            return [_E([0.1] * 1536) for _ in texts]

    monkeypatch.setattr(librarian, "get_embedding_provider", lambda: _StubProvider())
    monkeypatch.setattr(librarian, "vector_search_chunks", lambda emb, top_k, **kw: [])

    captured = []

    def _capture(chunks):
        captured.extend(chunks)

    monkeypatch.setattr(librarian, "vector_upsert_chunks", _capture)

    payload = await librarian.archive(
        task_id="t-good",
        note_path=str(note),
        paths=paths,
    )

    # Archive succeeded — chunks were written.
    assert payload.chunk_count > 0
    assert captured, "vector_upsert_chunks must be called when embeddings exist"