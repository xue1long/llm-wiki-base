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
    evidence_refs: tuple[str, ...] = ()
    provenance: str | None = None
    knowledge_mode: str | None = None
    context: dict[str, Any] | None = None
    validity: dict[str, Any] | None = None
    publication_version: int | None = None
    version: int | None = None


def _normalize_evidence_refs(
    value: dict[str, Any],
    evidence: tuple[RetrievalEvidence, ...],
) -> tuple[str, ...]:
    raw_refs = value.get("evidence_refs")
    if isinstance(raw_refs, (list, tuple)):
        return tuple(str(item) for item in raw_refs if item not in (None, ""))
    return tuple(
        f"{item.document_id}:{item.block_id}" if item.document_id else item.block_id
        for item in evidence
        if item.block_id
    )


def _normalize_optional_int(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    return int(raw)


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
    raw_provenance = value.get("provenance")
    raw_context = value.get("context")
    raw_validity = value.get("validity")
    return RetrievalResult(
        id=str(value.get("id") or value.get("page_id") or value.get("path", "")),
        title=str(value.get("title", "")),
        score=float(value.get("score", 0.0)),
        content=str(value.get("content", value.get("snippet", ""))),
        evidence=evidence,
        evidence_refs=_normalize_evidence_refs(value, evidence),
        provenance=str(raw_provenance) if raw_provenance not in (None, "") else None,
        knowledge_mode=(
            str(value.get("knowledge_mode"))
            if value.get("knowledge_mode") not in (None, "")
            else None
        ),
        context=raw_context if isinstance(raw_context, dict) else None,
        validity=raw_validity if isinstance(raw_validity, dict) else None,
        publication_version=_normalize_optional_int(value.get("publication_version")),
        version=_normalize_optional_int(value.get("version")),
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
