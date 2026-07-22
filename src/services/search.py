"""Search service — dispatches to the hybrid (semantic + keyword) searcher.

Extracted from src/server/routes/search.py. Validates the project,
delegates to src.searcher.hybrid_search.hybrid_search, and shapes the
response for the HTTP layer.

Note: The underlying hybrid_search function only takes (query, top_k=10).
The previous route incorrectly passed (ctx, query, top_k, mode) — mode
is preserved in the response for the client's reference but is not
honoured by the underlying implementation.
"""
from __future__ import annotations

from ..lib.project import resolve_project
from ..searcher.hybrid_search import hybrid_search


async def search(
    project_id: str,
    query: str,
    top_k: int = 10,
    mode: str = "hybrid",
) -> dict:
    """Search the project's wiki tree and return ranked results.

    Returns a dict ready for the HTTP route:
        {
            "query": str,
            "mode": str,           # passed-through; not used by hybrid_search
            "topK": int,           # echoed for the client
            "tokenHits": 0,        # reserved (not populated by current impl)
            "vectorHits": 0,       # reserved (not populated by current impl)
            "results": list[SearchResult],
        }
    """
    # Validate the project exists (raises ProjectNotFound otherwise)
    resolve_project(project_id, by_id_only=True)

    results = await hybrid_search(query, top_k=top_k)
    return {
        "query": query,
        "mode": mode,
        "topK": top_k,
        "tokenHits": 0,
        "vectorHits": 0,
        "results": results,
    }
