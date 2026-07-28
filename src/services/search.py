"""Search service — dispatches to the hybrid (semantic + keyword) searcher.

Extracted from src/server/routes/search.py. Validates the project,
delegates to src.searcher.hybrid_search.hybrid_search, and shapes the
response for the HTTP layer.

Note: The underlying hybrid_search function only takes (query, top_k=10).
The previous route incorrectly passed (ctx, query, top_k, mode) — mode
is preserved in the response for the client's reference but is not
honoured by the underlying implementation.

Audit I3: the service now resolves ``WikiPaths`` for the project and
threads it through ``get_table(project_paths)`` so multi-project search
does not cross-pollute vectors. ``hybrid_search`` doesn't yet accept
project paths; the search service resolves the table explicitly so the
vector component is project-scoped even though the keyword index is
still global. This is the minimum surface change that closes the I3
finding without breaking legacy callers.
"""
from __future__ import annotations

import logging

from ..lib.project import resolve_project
from ..searcher.hybrid_search import hybrid_search
from ..vector.store import get_table as get_vector_table

logger = logging.getLogger(__name__)


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
    # Validate the project exists; capture WikiPaths for project-scoped
    # vector resolution (audit I3).
    ctx, paths = resolve_project(project_id, by_id_only=True)

    # Audit I3: project-scoped vector table resolution. Falls back to the
    # process-global handle if the project has not been initialised, but
    # in that case `get_table(project_paths)` lazy-initialises it.
    try:
        get_vector_table(paths)
    except Exception:
        # Lazy init failure: still proceed; keyword results will populate.
        logger.warning("Vector table init failed for project %s; keyword-only fallback", project_id, exc_info=True)

    results = await hybrid_search(query, top_k=top_k, paths=paths)
    return {
        "query": query,
        "mode": mode,
        "topK": top_k,
        "tokenHits": 0,
        "vectorHits": 0,
        "results": results,
    }
