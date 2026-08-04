"""Web search abstraction layer — multi-provider support.

Supports Tavily, SerpApi, and SearXNG as search providers.
Phase 2.3 of the Nash absorption plan.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class SearchProvider(str, Enum):
    """Available web search providers."""

    TAVILY = "tavily"
    SERPAPI = "serpapi"
    SEARXNG = "searxng"


@dataclass
class WebSearchResult:
    """A single web search result."""

    title: str
    url: str
    snippet: str
    source: str  # Provider name

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


class WebSearchProviderBase(ABC):
    """Abstract base class for web search providers."""

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[WebSearchResult]:
        """Execute a search query and return results."""
        ...


class TavilyProvider(WebSearchProviderBase):
    """Tavily search provider (recommended for production)."""

    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 10) -> list[WebSearchResult]:
        """Search using Tavily API."""
        try:
            from tavily import TavilyClient
        except ImportError:
            raise ImportError(
                "tavily-python is required for Tavily search. "
                "Install with: pip install tavily-python>=0.3.0"
            )

        client = TavilyClient(api_key=self.api_key)
        response = client.search(query, max_results=max_results)

        return [
            WebSearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                source=self.name,
            )
            for r in response.get("results", [])
        ]


class SerpApiProvider(WebSearchProviderBase):
    """SerpApi search provider."""

    name = "serpapi"

    def __init__(self, api_key: str, engine: str = "google"):
        self.api_key = api_key
        self.engine = engine

    async def search(self, query: str, max_results: int = 10) -> list[WebSearchResult]:
        """Search using SerpApi."""
        import json
        import urllib.parse
        import urllib.request

        params = {
            "api_key": self.api_key,
            "q": query,
            "engine": self.engine,
            "num": max_results,
        }
        url = f"https://serpapi.com/search?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
        except Exception as e:
            raise RuntimeError(f"SerpApi request failed: {e}") from e

        results = []
        for item in data.get("organic_results", [])[:max_results]:
            results.append(WebSearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source=self.name,
            ))

        return results


class SearXNGProvider(WebSearchProviderBase):
    """SearXNG self-hosted search provider."""

    name = "searxng"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, max_results: int = 10) -> list[WebSearchResult]:
        """Search using SearXNG instance."""
        import json
        import urllib.parse
        import urllib.request

        params = {
            "q": query,
            "format": "json",
        }
        url = f"{self.base_url}/search?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
        except Exception as e:
            raise RuntimeError(f"SearXNG request failed: {e}") from e

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(WebSearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source=self.name,
            ))

        return results


# Provider registry
_providers: dict[str, WebSearchProviderBase] = {}


def register_provider(name: str, provider: WebSearchProviderBase) -> None:
    """Register a search provider."""
    _providers[name] = provider


def get_provider(name: str) -> WebSearchProviderBase:
    """Get a registered provider."""
    if name not in _providers:
        raise ValueError(f"Unknown search provider: {name}. Available: {list(_providers.keys())}")
    return _providers[name]


def list_providers() -> list[str]:
    """List registered providers."""
    return list(_providers.keys())


async def web_search(query: str, provider: str = "tavily", max_results: int = 10) -> list[WebSearchResult]:
    """Execute a web search using the specified provider.

    Args:
        query: Search query
        provider: Provider name (default: tavily)
        max_results: Maximum results to return

    Returns:
        List of WebSearchResult
    """
    p = get_provider(provider)
    return await p.search(query, max_results)