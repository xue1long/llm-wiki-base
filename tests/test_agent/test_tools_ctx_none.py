"""Regression: tools must handle ctx=None gracefully.

WikiSearchTool already had the guard. The other four tools (read_page,
source.search, graph.search, web.search) used to dereference
ctx.path unconditionally — any caller passing ctx=None (e.g. a unit
test, or a future agent that delegates without a project context)
hit AttributeError.
"""
import asyncio

from src.agent.tools import (
    GraphSearchTool,
    SourceSearchTool,
    WikiReadPageTool,
    WebSearchTool,
)


def _run(coro):
    return asyncio.run(coro)


def test_wiki_read_page_handles_none_ctx():
    tool = WikiReadPageTool()
    result = _run(tool.execute(ctx=None, path="foo.md"))
    assert "error" in result
    assert "ctx is required" in result["error"]


def test_source_search_handles_none_ctx():
    tool = SourceSearchTool()
    result = _run(tool.execute(ctx=None, query="keyword", top_k=5))
    assert result["query"] == "keyword"
    assert result["results"] == []
    assert "error" in result
    assert "ctx is required" in result["error"]


def test_graph_search_handles_none_ctx():
    tool = GraphSearchTool()
    result = _run(tool.execute(ctx=None, query="keyword", top_k=5))
    assert result["query"] == "keyword"
    assert result["matches"] == []
    assert "error" in result
    assert "ctx is required" in result["error"]



def test_ctx_none_error_shapes_are_consistent():
    """All three tools must return the same error-dict shape when ctx=None:
    {"error": "...", "query": <the requested query or None>, "results"|"matches": []}.
    Callers should be able to rely on the same keys regardless of which
    tool raised the guard.
    """
    read = WikiReadPageTool()
    src = SourceSearchTool()
    graph = GraphSearchTool()

    r_read = _run(read.execute(ctx=None, path="any.md"))
    r_src = _run(src.execute(ctx=None, query="kw", top_k=5))
    r_graph = _run(graph.execute(ctx=None, query="kw", top_k=5))

    for label, result in [("wiki.read_page", r_read), ("source.search", r_src), ("graph.search", r_graph)]:
        assert "error" in result, f"{label} error missing 'error' key"
        assert "ctx is required" in result["error"], f"{label} error missing 'ctx is required' substring"
        assert "query" in result, f"{label} missing 'query' key (should be None for read_page)"
        # read_page uses None, search tools use the requested query string.
        if label == "wiki.read_page":
            assert result["query"] is None
        else:
            assert result["query"] == "kw"
