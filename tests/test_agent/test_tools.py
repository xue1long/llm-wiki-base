"""Tests for src/agent/tools.py — 5 MVP tools."""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Stub out the real hybrid_search module BEFORE importing src.agent.tools,
# since lancedb (a transitive import) may not be installed in this env.
# The brief notes this — hybrid_search signature differs from the real one.
def _install_hybrid_search_stub():
    """Create a stub for src.searcher.hybrid_search that won't import lancedb,
    but exposes the same names as the real module so subsequent test_searcher
    imports (MAX_TOP_K, rrf_fusion, SearchResult) don't fail. Also stub
    src.searcher.qa and src.searcher.searcher since test_searcher imports from
    those too.
    """
    if getattr(sys.modules.get("lancedb"), "__file__", None) is not None:
        return
    searcher_pkg = types.ModuleType("src.searcher")
    searcher_pkg.__path__ = [str(Path(__file__).parents[2] / "src" / "searcher")]
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
    """Helper: run async coroutine to completion."""
    return asyncio.run(coro)


@pytest.fixture
def ctx(tmp_path):
    """Mock ProjectContext with path attribute (WikiPaths is constructed from it)."""
    ctx = MagicMock()
    ctx.path = tmp_path
    # Legacy ctx.paths attributes still set for backward-compat checks
    ctx.paths.root = tmp_path
    ctx.paths.raw_sources = tmp_path / "raw"
    ctx.paths.wiki_sources = tmp_path / "wiki_sources"
    ctx.paths.wiki_entities = tmp_path / "wiki_entities"
    ctx.paths.wiki_concepts = tmp_path / "wiki_concepts"
    ctx.paths.wiki_synthesis = tmp_path / "wiki_synthesis"
    return ctx


def test_wiki_search_returns_results(ctx):
    """wiki.search dispatches to hybrid_search and returns its results."""
    fake_results = [{"path": "a.md", "title": "A", "score": 0.9}]

    async def fake_hybrid_search(query, top_k=10, paths=None):
        return fake_results

    with patch("src.agent.tools.hybrid_search", new=fake_hybrid_search):
        from src.agent.tools import WikiSearchTool
        result = _run(WikiSearchTool().execute(ctx, query="hello", top_k=3))
    assert result["query"] == "hello"
    assert result["results"] == fake_results


def test_wiki_read_page(tmp_path):
    """wiki.read_page reads a markdown file with YAML frontmatter and returns body fields."""
    from src.wiki.core.types import PageType, WikiPage
    import yaml

    # Create a real wiki page on disk
    wiki_dir = tmp_path / "wiki_entities"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    page_path = wiki_dir / "alice.md"
    page = WikiPage(
        id="alice",
        title="Alice",
        type=PageType.ENTITY,
        sources=[],
        body="Alice is a character.",
    )
    fm = yaml.dump(page.to_frontmatter_dict(), allow_unicode=True, sort_keys=False, default_flow_style=False)
    page_path.write_text(f"---\n{fm}---\n\n{page.body}", encoding="utf-8")

    # Mock ctx with path and paths.root pointing at tmp_path
    ctx = MagicMock()
    ctx.path = tmp_path
    ctx.paths.root = tmp_path

    from src.agent.tools import WikiReadPageTool
    # Pass a relative path so the tool joins it with paths.root
    result = _run(WikiReadPageTool().execute(ctx, path="wiki_entities/alice.md"))

    assert result["id"] == "alice"
    assert result["title"] == "Alice"
    assert result["type"] == "entity"
    assert "Alice is a character." in result["body"]


def test_web_search_no_provider(ctx):
    """web.search with no tavily/searxng provider returns empty with explanatory provider string."""
    from src.llm.registry import ProviderNotFoundError
    # ProviderRegistry is imported lazily inside execute(), so patch the source module.
    with patch("src.llm.registry.ProviderRegistry") as MockRegistry:
        # tools.py migrated from load()+in to require(); patch require() to raise
        # so the named-lookup chain falls through to the "no web search configured" branch.
        MockRegistry.require.side_effect = ProviderNotFoundError("not configured")
        from src.agent.tools import WebSearchTool
        result = _run(WebSearchTool().execute(ctx, query="test", top_k=5))

    assert result["query"] == "test"
    assert result["results"] == []
    assert "no web search configured" in result["provider"]
