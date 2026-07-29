# ruflo-kb/tests/test_pipeline/test_librarian_validates_existing_path.py
"""Verify librarian.archive rejects existing_path values that fall outside
the project knowledge_dir.

Before the fix: archive wrote to ``Path(\"Knowledge\")`` (CWD-relative) and
_merge_duplicates wrote to whatever path the vector store returned, with
no validation. This was both CWD-unsafe and a path-injection vector.
After the fix: archive takes a ``paths: WikiPaths`` parameter and rejects
existing_path values that resolve outside ``paths.knowledge_dir``.
"""
import pytest

from src.wiki.core.paths import WikiPaths
from src.pipeline import librarian


class _FakeResult:
    def __init__(self, path: str, score: float = 0.99):
        self.path = path
        self.score = score


@pytest.mark.asyncio
async def test_merge_duplicates_rejects_path_outside_knowledge_dir(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.knowledge_dir.mkdir(parents=True, exist_ok=True)

    # existing_path resolves to a sibling directory of project_root — outside knowledge_dir
    outside = tmp_path / "other" / "evil.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("hi", encoding="utf-8")

    with pytest.raises(PermissionError):
        await librarian._merge_duplicates(
            task_id="t1",
            new_path="some_new.md",
            new_content="new content",
            similar_result=_FakeResult(path=str(outside)),
            paths=paths,
        )


@pytest.mark.asyncio
async def test_merge_duplicates_accepts_path_inside_knowledge_dir(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.knowledge_dir.mkdir(parents=True, exist_ok=True)

    inside = paths.knowledge_dir / "good.md"
    inside.write_text("original", encoding="utf-8")

    # Should NOT raise — path is inside knowledge_dir
    # Pass paths=paths so the is_relative_to validation actually runs.
    payload = await librarian._merge_duplicates(
        task_id="t2",
        new_path="new.md",
        new_content="new",
        similar_result=_FakeResult(path=str(inside)),
        paths=paths,
    )
    assert payload.existing_path == str(inside)
    assert "合并来源" in payload.merged_content


@pytest.mark.asyncio
async def test_archive_propagates_permission_error_for_out_of_root_path(tmp_path, monkeypatch):
    """Regression: archive() must NOT swallow the PermissionError raised by
    _merge_duplicates when vector_search returns an out-of-root path.

    Before the fix, _merge_duplicates was called inside the broad
    embedding-search ``except Exception``, so a corrupt vector-store result
    pointing outside knowledge_dir was logged and ignored — archive() would
    proceed to create a new file. This test monkeypatches vector_search_chunks
    to return an out-of-root path and asserts PermissionError propagates.
    """
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(root=project_root)
    paths.knowledge_dir.mkdir(parents=True, exist_ok=True)

    # Note to archive
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nSome content here.", encoding="utf-8")

    # Out-of-root "existing" path that vector_search will pretend exists
    outside = tmp_path / "other" / "evil.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("evil", encoding="utf-8")

    # Stub out the embedding + vector_search chain so we always get a "hit"
    # pointing outside knowledge_dir. Use a tiny embedding provider that
    # satisfies the protocol.
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

    with pytest.raises(PermissionError):
        await librarian.archive(
            task_id="t3",
            note_path=str(note),
            paths=paths,
        )
