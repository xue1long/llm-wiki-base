"""Search service — dispatches to the hybrid (semantic + keyword) searcher.

Extracted from src/server/routes/search.py. Validates the project,
delegates to src.searcher.hybrid_search.hybrid_search, and shapes the
response for the HTTP layer.

The service passes the requested mode to the underlying searcher and blocks
semantic writing search when the project's Wiki/Vector state is not ready.

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
from ..llm.embedding_runtime import get_embedding_provider
from ..searcher.hybrid_search import hybrid_search
from ..vector.pending import readiness as vector_readiness
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

    if mode not in {"hybrid", "keyword", "vector"}:
        raise ValueError(f"unsupported search mode: {mode}")
    if mode == "keyword":
        status = {"ready": True, "reason": "keyword"}
    else:
        model = ""
        try:
            provider = get_embedding_provider()
            model = str(getattr(provider, "model", "") or getattr(provider, "_model_name", ""))
        except RuntimeError:
            pass
        status = vector_readiness(paths, embedding_model=model)
    if mode != "keyword" and status["ready"]:
        try:
            get_vector_table(paths)
        except Exception:
            logger.warning("Vector table init failed for project %s", project_id, exc_info=True)
            status = {**status, "ready": False, "reason": "unavailable"}

    if mode != "keyword" and not status["ready"]:
        results = []
    else:
        results = await hybrid_search(query, top_k=top_k, paths=paths, mode=mode)
        if mode in {"hybrid", "vector"}:
            results = _filter_actionable(paths, results)

    # Post-filter by PageType if requested (1.2.3).
    if page_type:
        results = _filter_by_page_type(paths, results, page_type)

    return {
        "query": query,
        "mode": mode,
        "topK": top_k,
        "tokenHits": 0,
        "vectorHits": 0,
        "ready": status["ready"] if mode != "keyword" else True,
        "diagnostics": status if mode != "keyword" else {"ready": True, "reason": "keyword"},
        "results": results,
    }


def _filter_actionable(paths, results: list) -> list:
    """Keep only human-approved actionable pages for semantic writing search."""
    import yaml
    from pathlib import Path
    from ..utils.path import safe_resolve

    filtered = []
    for result in results:
        raw_path = str(result.get("path", "")).replace("\\", "/")
        if raw_path.startswith("wiki/"):
            raw_path = raw_path[5:]
        candidate = safe_resolve(paths.wiki / Path(raw_path))
        if not candidate.exists() or not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        try:
            frontmatter = yaml.safe_load(text[4:end]) or {}
        except yaml.YAMLError:
            continue
        if "用途/可执行" in (frontmatter.get("tags") or []):
            filtered.append(result)
    return filtered


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
