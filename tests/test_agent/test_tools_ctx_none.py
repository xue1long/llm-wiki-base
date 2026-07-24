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
