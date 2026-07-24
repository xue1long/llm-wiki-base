# ruflo-kb/src/searcher/hybrid_search.py
"""Hybrid semantic + keyword search across the wiki.

Embedding provider is sourced from ``src.llm.embedding_runtime`` (the
process-global singleton). Initialisation happens at app startup.
"""
import logging
import re
from pathlib import Path
from typing import TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..vector.search import ChunkSearchResult

from ..llm.embedding_runtime import (
    get_embedding_provider as _runtime_get_embedding_provider,
)
from ..vector.search import vector_search_chunks

logger = logging.getLogger(__name__)

#: Default cap for ``top_k`` in :func:`hybrid_search`. Callers requesting
#: more than this raise :class:`ValueError`.
MAX_TOP_K: int = 100


class SearchResult(TypedDict):
    path: str
    title: str
    content: str
    score: float
    source: str


# Public re-export — preserves the prior ``hybrid_search.get_embedding_provider``
# attribute surface for downstream callers.
get_embedding_provider = _runtime_get_embedding_provider


def rrf_fusion(
    semantic_results: list[SearchResult],
    keyword_results: list[SearchResult],
    k: int = 60,
) -> list[SearchResult]:
    """Reciprocal Rank Fusion over two SEPARATE lists.

    Each list's contribution is ``sum(1 / (k + rank))`` for each doc that
    appears in that list; then merge across lists by sum and sort desc.

    If one list is empty, the other list's results are returned (not an
    empty list) — an empty list on one side is normal degradation, not
    a request for zero results.

    Returns a new list of :class:`SearchResult` dicts with ``score`` set
    to the fused RRF score.
    """
    if not semantic_results and not keyword_results:
        return []

    scores: dict[str, float] = {}
    # Track the source-result dict per path so we can return SearchResult
    # objects with metadata. Prefer semantic (richer), fall back to keyword.
    by_path: dict[str, SearchResult] = {}

    for i, item in enumerate(semantic_results):
        key = item["path"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + i + 1)
        by_path.setdefault(key, item)

    for i, item in enumerate(keyword_results):
        key = item["path"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + i + 1)
        by_path.setdefault(key, item)

    out: list[SearchResult] = []
    for path, fused_score in scores.items():
        result = dict(by_path[path])
        result["score"] = fused_score
        out.append(result)

    out.sort(key=lambda r: r["score"], reverse=True)
    return out


async def hybrid_search(
    query: str, top_k: int = 10, paths: "WikiPaths | None" = None,
) -> list[SearchResult]:
    """混合检索: 语义 + 关键词

    Validates inputs:
    - ``query.strip()`` must be non-empty (raises ``ValueError``)
    - ``1 <= top_k <= MAX_TOP_K`` (raises ``ValueError``)

    When ``paths`` is provided, the keyword search scans the v2
    wiki tree (``paths.knowledge_dir``). When ``None``, the keyword
    search falls back to the legacy CWD-relative ``Knowledge/`` and
    emits a deprecation warning — callers should pass the project's
    ``WikiPaths`` so keyword search actually finds v2 wiki pages.
    """
    if not query or not query.strip():
        raise ValueError("query cannot be empty")
    if not isinstance(top_k, int) or isinstance(top_k, bool):
        raise ValueError(f"top_k must be an int, got {type(top_k).__name__}")
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k}")
    if top_k > MAX_TOP_K:
        raise ValueError(f"top_k must be <= {MAX_TOP_K}, got {top_k}")

    # 1. 语义检索 (需要 embedding 服务)
    semantic_results: list[SearchResult] = []
    try:
        provider = get_embedding_provider()
        embedding_result = await provider.embed([query])
        # Normalise: accept either list[list[float]] or list[EmbeddingResponse].
        first = embedding_result[0]
        query_embedding = first.embedding if hasattr(first, "embedding") else first
        vector_results: list["ChunkSearchResult"] = vector_search_chunks(query_embedding, top_k)

        for r in vector_results:
            semantic_results.append(SearchResult(
                path=r.path,
                title=Path(r.path).stem,
                content=r.content[:300],
                score=r.score,
                source="semantic",
            ))
    except Exception as e:
        # Provider not configured, embed call failed, or vector search
        # unavailable. Fall through to keyword-only results. The runtime
        # raises RuntimeError when nothing has been configured; we log
        # the failure mode (class + reason, truncated to 200 chars) and
        # degrade gracefully to keyword-only.
        logger.warning(
            "hybrid_search: semantic retrieval failed (%s: %s); falling back to keyword-only",
            type(e).__name__,
            str(e)[:200],
        )

    # 2. 关键词检索
    keyword_results = await _keyword_search(query, top_k, paths=paths)

    # 3. RRF 融合 — always over TWO separate lists; if one side is empty
    # the other side's results are still returned (per the resolved
    # ambiguity in task-13 brief).
    if not semantic_results and not keyword_results:
        return []
    if not semantic_results:
        return keyword_results[:top_k]
    if not keyword_results:
        return semantic_results[:top_k]

    fused = rrf_fusion(semantic_results, keyword_results, k=60)
    return fused[:top_k]


async def _keyword_search(
    query: str, top_k: int, paths: "WikiPaths | None" = None,
) -> list[SearchResult]:
    """简单关键词检索

    When ``paths`` is provided, scan ``paths.knowledge_dir`` (the
    v2 wiki tree, alias for ``<root>/wiki``). When ``None``, fall back
    to the CWD-relative ``Knowledge/`` and emit a deprecation warning
    — v2 wikis store pages under ``<root>/wiki/`` and the legacy
    index is empty in real production runs.
    """
    results = []
    if paths is not None:
        knowledge_dir = paths.knowledge_dir
    else:
        logger.warning(
            "_keyword_search: paths is None — falling back to CWD-relative Knowledge/. Pass WikiPaths (e.g. via services/search.search) so keyword search actually finds v2 wiki pages. This fallback will be removed in 1.0."
        )
        knowledge_dir = Path("Knowledge")

    if not knowledge_dir.exists():
        return results

    query_lower = query.lower()

    for file in knowledge_dir.glob("*.md"):
        content = file.read_text(encoding="utf-8")
        content_lower = content.lower()

        if query_lower in content_lower:
            matches = len(re.findall(re.escape(query_lower), content_lower))
            title_match = 2 if query_lower in file.stem.lower() else 0

            results.append(SearchResult(
                path=str(file),
                title=file.stem,
                content=content[:300],
                score=float(matches + title_match),
                source="keyword",
            ))

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
