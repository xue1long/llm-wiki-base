# ruflo-kb/src/searcher/hybrid_search.py
import re
from pathlib import Path
from typing import TypedDict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import EmbeddingProvider
    from ..vector.search import ChunkSearchResult

from ..vector.search import vector_search_chunks

class SearchResult(TypedDict):
    path: str
    title: str
    content: str
    score: float
    source: str

_embedding_provider: Optional["EmbeddingProvider"] = None

def set_embedding_provider(provider: "EmbeddingProvider") -> None:
    """设置全局 embedding provider"""
    global _embedding_provider
    _embedding_provider = provider

def get_embedding_provider() -> Optional["EmbeddingProvider"]:
    """获取全局 embedding provider"""
    return _embedding_provider

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
    if _embedding_provider:
        try:
            embedding_result = await _embedding_provider.embed([query])
            query_embedding = embedding_result[0].embedding
            vector_results: list[ChunkSearchResult] = vector_search_chunks(query_embedding, top_k)

            for r in vector_results:
                semantic_results.append(SearchResult(
                    path=r.path,
                    title=Path(r.path).stem,
                    content=r.content[:300],
                    score=r.score,
                    source="semantic",
                ))
        except Exception:
            pass  # Fallback to keyword only

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
