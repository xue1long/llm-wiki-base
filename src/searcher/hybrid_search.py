# ruflo-kb/src/searcher/hybrid_search.py
"""Hybrid semantic + keyword search across the wiki.

Embedding provider is sourced from ``src.llm.embedding_runtime`` (the
process-global singleton). Initialisation happens at app startup.
"""
import re
from pathlib import Path
from typing import TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..vector.search import ChunkSearchResult

from ..llm.embedding_runtime import (
    get_embedding_provider as _runtime_get_embedding_provider,
)
from ..vector.search import vector_search_chunks


class SearchResult(TypedDict):
    path: str
    title: str
    content: str
    score: float
    source: str


# Public re-export — preserves the prior ``hybrid_search.get_embedding_provider``
# attribute surface for downstream callers.
get_embedding_provider = _runtime_get_embedding_provider


def rrf_fusion(items: list, k: int = 60) -> dict:
    """Reciprocal Rank Fusion"""
    scores = {}
    for i, item in enumerate(items):
        key = item["path"]
        score = scores.get(key, 0)
        scores[key] = score + 1 / (k + i + 1)
    return scores


async def hybrid_search(query: str, top_k: int = 10) -> list[SearchResult]:
    """混合检索: 语义 + 关键词"""
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
    except Exception:
        # Provider not configured, embed call failed, or vector search
        # unavailable. Fall through to keyword-only results. The runtime
        # raises RuntimeError when nothing has been configured; we swallow
        # it here so search degrades gracefully to keyword-only.
        pass

    # 2. 关键词检索
    keyword_results = await _keyword_search(query, top_k)

    # 3. RRF 融合
    if semantic_results and keyword_results:
        # 融合两种结果
        fused_scores = rrf_fusion([*semantic_results, *keyword_results])
        all_results = {**{r["path"]: r for r in semantic_results},
                       **{r["path"]: r for r in keyword_results}}

        for path, fused_score in fused_scores.items():
            if path in all_results:
                all_results[path]["score"] = fused_score

        sorted_results = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)
        return sorted_results[:top_k]

    return keyword_results[:top_k]


async def _keyword_search(query: str, top_k: int) -> list[SearchResult]:
    """简单关键词检索"""
    results = []
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
