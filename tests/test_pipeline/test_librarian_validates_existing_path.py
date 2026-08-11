"""Verify librarian._merge_duplicates tolerates existing_path values that
fall outside the project knowledge_dir (or outside root / missing on disk).

Before the cross-device fix: a stored path from a different machine's
absolute root (e.g. OneDrive ``C:\\...`` vs current ``D:\\...``) raised
``PermissionError``, failing the whole archive. After the fix: foreign /
stale / missing existing_path values make _merge_duplicates return ``None``
so archive() skips the merge and archives normally (self-heal).
"""
import pytest

from src.wiki.core.paths import WikiPaths
from src.pipeline import librarian


class _FakeResult:
    def __init__(self, path: str, score: float = 0.99):
        self.path = path
        self.score = score


@pytest.mark.asyncio
async def test_merge_duplicates_returns_none_for_path_outside_knowledge_dir(tmp_path):
    """Outside knowledge_dir but inside root -> None (skip merge)."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    # existing_path resolves inside root (raw/) but outside knowledge_dir (wiki/)
    outside_kb = project_root / "raw" / "sources" / "evil.md"
    outside_kb.parent.mkdir(parents=True, exist_ok=True)
    outside_kb.write_text("hi", encoding="utf-8")

    result = await librarian._merge_duplicates(
        task_id="t1",
        new_path=str(paths.wiki_sources / "new.md"),
        new_content="new content",
        similar_result=_FakeResult(path=str(outside_kb)),
        paths=paths,
    )
    assert result is None


@pytest.mark.asyncio
async def test_merge_duplicates_returns_none_for_foreign_absolute_path(tmp_path):
    """A stored path from another device (outside current root) -> None."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "sibling" / "evil.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("hi", encoding="utf-8")

    result = await librarian._merge_duplicates(
        task_id="t1b",
        new_path=str(paths.wiki_sources / "new.md"),
        new_content="new content",
        similar_result=_FakeResult(path=str(outside)),
        paths=paths,
    )
    assert result is None


@pytest.mark.asyncio
async def test_merge_duplicates_returns_none_for_missing_file(tmp_path):
    """existing_path resolves inside knowledge_dir but the file is gone -> None."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    missing = paths.wiki_sources / "deleted.md"  # does not exist on disk

    result = await librarian._merge_duplicates(
        task_id="t1c",
        new_path=str(paths.wiki_sources / "new.md"),
        new_content="new content",
        similar_result=_FakeResult(path=str(missing)),
        paths=paths,
    )
    assert result is None


@pytest.mark.asyncio
async def test_merge_duplicates_accepts_path_inside_knowledge_dir(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    inside = paths.wiki_sources / "good.md"
    inside.write_text("original", encoding="utf-8")

    payload = await librarian._merge_duplicates(
        task_id="t2",
        new_path=str(paths.wiki_sources / "new.md"),
        new_content="new",
        similar_result=_FakeResult(path=str(inside)),
        paths=paths,
    )
    assert payload is not None
    assert payload.existing_path == str(inside)
    assert "合并来源" in payload.merged_content


@pytest.mark.asyncio
async def test_archive_skips_merge_and_upserts_when_existing_path_foreign(tmp_path, monkeypatch):
    """Regression: archive() must NOT fail when vector_search returns a foreign
    path; it should skip the merge and archive normally (upsert new vectors).
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.wiki_sources.mkdir(parents=True, exist_ok=True)

    # Note to archive — inside the project so its stored path is relative.
    note = paths.wiki_sources / "note.md"
    note.write_text("# Note\n\nSome content here.", encoding="utf-8")

    # Foreign "existing" path (a different device's absolute root).
    outside = tmp_path / "other" / "evil.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("evil", encoding="utf-8")

    class _StubProvider:
        async def embed(self, chunks):
            class _E:
                def __init__(self, embedding):
                    self.embedding = embedding
            return [_E([0.0] * 1536) for _ in chunks]

    monkeypatch.setattr(librarian, "get_embedding_provider", lambda: _StubProvider())
    monkeypatch.setattr(
        librarian,
        "vector_search_chunks",
        lambda emb, top_k, **kw: [_FakeResult(path=str(outside), score=0.99)],
    )

    captured = []

    def _capture(chunks):
        captured.extend(chunks)

    monkeypatch.setattr(librarian, "vector_upsert_chunks", _capture)

    payload = await librarian.archive(
        task_id="t3",
        note_path=str(note),
        paths=paths,
    )

    # Foreign path must NOT raise; archive completes with new vectors upserted.
    assert captured, "vector_upsert_chunks must be called when merge is skipped"
    assert all(c.path == "wiki/sources/note.md" for c in captured)
