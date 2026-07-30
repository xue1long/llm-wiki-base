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
    page_type: str | None = None,
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
        logger.warning("Vector table init failed for project %s; keyword-only fallback", project_id, exc_info=True)

    results = await hybrid_search(query, top_k=top_k, paths=paths)

    # Post-filter by PageType if requested (1.2.3).
    if page_type:
        results = _filter_by_page_type(paths, results, page_type)

    return {
        "query": query,
        "mode": mode,
        "topK": top_k,
        "tokenHits": 0,
        "vectorHits": 0,
        "results": results,
    }


def _filter_by_page_type(paths, results: list, page_type: str) -> list:
    """Filter search results to only include pages matching page_type."""
    import yaml
    from pathlib import Path

    from ..utils.path import safe_resolve

    wiki_root = paths.wiki
    filtered = []
    for r in results:
        p = r.get("path", "")
        # Normalize: strip backslashes and "wiki/" prefix
        normalized = Path(p.replace("\\", "/").replace("wiki/", "", 1) if p.replace("\\", "/").startswith("wiki/") else p.replace("\\", "/"))
        candidate = safe_resolve(wiki_root / normalized)
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except Exception:
            continue
        if text.startswith("---\n"):
            end = text.find("\n---", 4)
            if end > 0:
                try:
                    fm = yaml.safe_load(text[4:end]) or {}
                except yaml.YAMLError:
                    continue
                if fm.get("type") == page_type:
                    filtered.append(r)
    return filtered
