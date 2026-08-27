"""Minimal retrieval contract over existing search and relation services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class RetrievalEvidence:
    document_id: str
    block_id: str
    quote: str
    status: str = "verified"


@dataclass(frozen=True)
class RetrievalResult:
    id: str
    title: str
    score: float
    content: str = ""
    evidence: tuple[RetrievalEvidence, ...] = ()
    provenance: str = "legacy"


def normalize_result(value: dict[str, Any]) -> RetrievalResult:
    evidence = tuple(
        RetrievalEvidence(
            document_id=str(item.get("document_id", "")),
            block_id=str(item["block_id"]),
            quote=str(item.get("quote", "")),
        )
        for item in value.get("evidence", ())
        if isinstance(item, dict) and item.get("block_id")
    )
    return RetrievalResult(
        id=str(value.get("id") or value.get("page_id") or value.get("path", "")),
        title=str(value.get("title", "")),
        score=float(value.get("score", 0.0)),
        content=str(value.get("content", value.get("snippet", ""))),
        evidence=evidence,
        provenance="evidence" if evidence else "legacy",
    )


async def search(query: str, search_fn: Callable[[str], Awaitable[dict]]) -> list[RetrievalResult]:
    response = await search_fn(query)
    return [normalize_result(item) for item in response.get("results", ())]


async def search_project(paths, query: str, top_k: int = 10, search_fn=None) -> list[RetrievalResult]:
    """Run the existing hybrid search against one project and normalize it."""
    if search_fn is None:
        from src.searcher.hybrid_search import hybrid_search
        search_fn = hybrid_search

    results = await search_fn(query, top_k=top_k, paths=paths)
    return [normalize_result(item) for item in results]


def get_evidence(result: RetrievalResult) -> tuple[RetrievalEvidence, ...]:
    return result.evidence


def get_relations(paths, page_id: str) -> list:
    from src.services.wiki_analysis import get_relations_for_page

    return get_relations_for_page(paths, page_id)
