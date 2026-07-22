"""5 MVP tools: wiki.search / wiki.read_page / source.search / graph.search / web.search."""
import asyncio
import logging
from typing import Protocol

from ..searcher.hybrid_search import hybrid_search
from ..wiki import PageType, page_path_for, read_page


_logger = logging.getLogger(__name__)


class Tool(Protocol):
    name: str
    description: str

    async def execute(self, ctx, **params) -> dict: ...


class WikiSearchTool:
    name = "wiki.search"
    description = "Hybrid search wiki/ pages"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        results = await hybrid_search(ctx, query, top_k=top_k, mode="hybrid")
        return {"query": query, "results": results}


class WikiReadPageTool:
    name = "wiki.read_page"
    description = "Read a wiki page by ID or path"

    async def execute(self, ctx, path: str) -> dict:
        from pathlib import Path
        if not Path(path).is_absolute():
            path = ctx.paths.root / path
        if not path.exists():
            return {"error": f"Not found: {path}"}
        page = read_page(path)
        return {
            "id": page.id, "title": page.title, "type": page.type.value,
            "body": page.body[:5000],
        }


class SourceSearchTool:
    name = "source.search"
    description = "Search raw/sources/ for keyword matches"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        results = []
        query_lower = query.lower()
        for src_file in ctx.paths.raw_sources.glob("*"):
            if src_file.suffix in (".md", ".txt"):
                content = src_file.read_text(encoding="utf-8", errors="ignore")
                if query_lower in content.lower():
                    results.append({"path": str(src_file.relative_to(ctx.paths.root))})
                    if len(results) >= top_k:
                        break
        return {"query": query, "results": results}


class GraphSearchTool:
    name = "graph.search"
    description = "Find entity neighbors via wikilinks"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        from ..wiki.features.wikilink import extract_wikilinks
        from ..wiki.storage.page_writer import read_page
        matches = []
        for sub in [ctx.paths.wiki_sources, ctx.paths.wiki_entities,
                    ctx.paths.wiki_concepts, ctx.paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                p = read_page(f)
                if query.lower() in (p.title + " " + p.body).lower():
                    matches.append({"id": p.id, "title": p.title,
                                    "links": extract_wikilinks(p.body)[:10]})
                    if len(matches) >= top_k:
                        break
        return {"query": query, "matches": matches}


class WebSearchTool:
    name = "web.search"
    description = "Web search via Tavily or SearXNG (per LLM provider spec)"

    async def execute(self, ctx, query: str, top_k: int = 5) -> dict:
        # MVP: use Tavily if configured, else SearXNG, else return empty.
        # Named-lookup chain preserved as explicit ProviderRegistry.require() calls so
        # the fallback order (tavily → searxng → none) stays deterministic.
        from ..llm.registry import ProviderRegistry, ProviderNotFoundError
        for name in ("tavily", "searxng"):
            try:
                ProviderRegistry.require(name)
                # Reuse existing web search logic (in MVP: stub)
                return {"query": query, "results": [], "provider": name}
            except ProviderNotFoundError:
                continue
        return {"query": query, "results": [], "provider": "(no web search configured)"}


TOOLS = {
    "wiki.search": WikiSearchTool(),
    "wiki.read_page": WikiReadPageTool(),
    "source.search": SourceSearchTool(),
    "graph.search": GraphSearchTool(),
    "web.search": WebSearchTool(),
}