"""Tavily web search provider."""
import json
import logging

import httpx


_logger = logging.getLogger(__name__)


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30)

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        if not self.api_key:
            return []
        try:
            resp = await self.client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": top_k,
                    "search_depth": "advanced",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            _logger.warning(f"Tavily search failed for query {query!r}: {e}")
            return []
        return [
            {"title": r["title"], "url": r["url"], "snippet": r.get("content", "")}
            for r in data.get("results", [])
        ]

    async def close(self):
        await self.client.aclose()
