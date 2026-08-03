"""Test that src/agent/tools.py uses WikiPaths(ctx.path) correctly (not ctx.paths)."""
import asyncio
import sys
import types



# Stub hybrid_search to avoid lancedb import
def _install_hybrid_search_stub():
    """Create a stub for src.searcher.hybrid_search that won't import lancedb,
    but exposes the same names as the real module so subsequent test_searcher
    imports (MAX_TOP_K, rrf_fusion, SearchResult) don't fail. Also stub
    src.searcher.qa and src.searcher.searcher since test_searcher imports from
    those too.
    """
    searcher_pkg = types.ModuleType("src.searcher")
    sys.modules["src.searcher"] = searcher_pkg

    hybrid_mod = types.ModuleType("src.searcher.hybrid_search")

    async def _stub_hybrid_search(query, top_k=10, paths=None):
        return []

    hybrid_mod.hybrid_search = _stub_hybrid_search
    hybrid_mod.MAX_TOP_K = 100
    hybrid_mod.rrf_fusion = lambda *args, **kwargs: []
    hybrid_mod.SearchResult = dict
    hybrid_mod.get_embedding_provider = (
        __import__("src.llm.embedding_runtime", fromlist=["get_embedding_provider"])
        .get_embedding_provider
    )
    sys.modules["src.searcher.hybrid_search"] = hybrid_mod
    searcher_pkg.hybrid_search = hybrid_mod.hybrid_search

    # Add a module-level logger for tests that assert on it
    import logging as _logging
    hybrid_mod.logger = _logging.getLogger("src.searcher.hybrid_search")

    # Stub src.searcher.qa (test_searcher imports generate_answer from it)
    qa_mod = types.ModuleType("src.searcher.qa")
    async def _stub_generate_answer(*args, **kwargs):
        return ""
    qa_mod.generate_answer = _stub_generate_answer
    sys.modules["src.searcher.qa"] = qa_mod
    searcher_pkg.generate_answer = qa_mod.generate_answer

    # Stub src.searcher.searcher (no public surface; just needs to exist)
    searcher_mod = types.ModuleType("src.searcher.searcher")
    sys.modules["src.searcher.searcher"] = searcher_mod


_install_hybrid_search_stub()





def _run(coro):
    return asyncio.run(coro)


def test_wiki_read_page_tool_uses_paths(monkeypatch, tmp_path):
    """Verify WikiReadPageTool uses WikiPaths(ctx.path), not ctx.paths."""
    from src.agent.tools import WikiReadPageTool

    # Setup: create a wiki page
    wiki_sources = tmp_path / "wiki" / "sources"
    wiki_sources.mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\ntitle: Foo\ntype: source\n---\nbody\n",
        encoding="utf-8",
    )

    # Mock ctx with ONLY .path attribute
    class FakeCtx:
        def __init__(self, path):
            self.path = path

    ctx = FakeCtx(tmp_path)
    tool = WikiReadPageTool()
    # Use absolute path to avoid resolution issues
    result = _run(tool.execute(ctx, path=str(wiki_sources / "foo.md")))
    assert "Foo" in str(result)


def test_wiki_read_page_tool_does_not_call_ctx_paths(monkeypatch, tmp_path):
    """Regression: ctx.paths must NOT be accessed (it doesn't exist)."""
    from src.agent.tools import WikiReadPageTool

    # Setup: create a wiki page so the read succeeds
    wiki_sources = tmp_path / "wiki" / "sources"
    wiki_sources.mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\ntitle: Foo\ntype: source\n---\nbody\n",
        encoding="utf-8",
    )

    class ExplodingCtx:
        def __init__(self, path):
            self.path = path

        @property
        def paths(self):
            raise AssertionError("ctx.paths must not be accessed")

    ctx = ExplodingCtx(tmp_path)
    tool = WikiReadPageTool()
    # Should not raise AssertionError
    result = _run(tool.execute(ctx, path="foo"))


def test_source_search_tool_uses_paths(monkeypatch, tmp_path):
    """Verify SourceSearchTool uses WikiPaths(ctx.path)."""
    from src.agent.tools import SourceSearchTool

    raw_sources = tmp_path / "raw" / "sources"
    raw_sources.mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "test.md").write_text(
        "This is a test document with keyword content.", encoding="utf-8"
    )

    class FakeCtx:
        def __init__(self, path):
            self.path = path

    ctx = FakeCtx(tmp_path)
    tool = SourceSearchTool()
    result = _run(tool.execute(ctx, query="keyword", top_k=5))
    assert "results" in result
    assert len(result["results"]) > 0


def test_graph_search_tool_uses_paths(monkeypatch, tmp_path):
    """Verify GraphSearchTool uses WikiPaths(ctx.path)."""
    from src.agent.tools import GraphSearchTool

    # Create pages in each wiki subdirectory
    wiki_sources = tmp_path / "wiki" / "sources"
    wiki_entities = tmp_path / "wiki" / "entities"
    wiki_concepts = tmp_path / "wiki" / "concepts"
    wiki_synthesis = tmp_path / "wiki" / "synthesis"
    for d in [wiki_sources, wiki_entities, wiki_concepts, wiki_synthesis]:
        d.mkdir(parents=True)

    (wiki_sources / "test.md").write_text(
        "---\nid: test1\ntitle: Test Page\ntype: source\n---\nbody with keyword\n",
        encoding="utf-8",
    )

    class FakeCtx:
        def __init__(self, path):
            self.path = path

    ctx = FakeCtx(tmp_path)
    tool = GraphSearchTool()
    result = _run(tool.execute(ctx, query="keyword", top_k=5))
    assert "results" in result


def test_wiki_search_tool_calls_hybrid_search_without_mode_kwarg(monkeypatch):
    """Regression: WikiSearchTool must call hybrid_search(query, top_k) without mode/ctx."""
    from src.agent import tools

    called_with = []

    async def mock_hybrid_search(query, top_k=10, paths=None):
        called_with.append((query, top_k))
        return []

    monkeypatch.setattr(tools, "hybrid_search", mock_hybrid_search)

    tool = tools.WikiSearchTool()
    result = _run(tool.execute(ctx=None, query="test query", top_k=7))

    assert called_with == [("test query", 7)]
    assert "results" in result
