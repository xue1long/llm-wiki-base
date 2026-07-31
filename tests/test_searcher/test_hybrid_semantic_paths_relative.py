"""Semantic results from hybrid_search must be project-relative so they share
the same RRF fusion key as keyword results (which are also relative now).

A stored absolute-inside-root vector path is relativized by hybrid_search.
"""
import pytest

import importlib

from src.wiki.core.paths import WikiPaths

hs_module = importlib.import_module("src.searcher.hybrid_search")


class _FakeResult:
    def __init__(self, path: str, content: str = "...", score: float = 0.9):
        self.path = path
        self.content = content
        self.score = score


class _StubProvider:
    async def embed(self, texts):
        class _E:
            def __init__(self, embedding):
                self.embedding = embedding
        return [_E([0.1] * 1536) for _ in texts]


@pytest.mark.asyncio
async def test_hybrid_semantic_paths_relative(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    paths = WikiPaths(project_root)
    paths.wiki_sources.mkdir(parents=True)

    monkeypatch.setattr(hs_module, "get_embedding_provider", lambda: _StubProvider())
    # A stored ABSOLUTE path inside the project root -> must be relativized.
    abs_inside = str(paths.wiki_sources / "x.md")
    monkeypatch.setattr(
        hs_module,
        "vector_search_chunks",
        lambda emb, top_k, paths, **kw: [_FakeResult(path=abs_inside, content="...", score=0.9)],
    )

    results = await hs_module.hybrid_search("query", top_k=10, paths=paths)
    sem = [r for r in results if r["source"] == "semantic"]
    assert sem, "expected a semantic result"
    assert sem[0]["path"] == "wiki/sources/x.md"
