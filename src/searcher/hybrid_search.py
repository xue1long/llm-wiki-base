# ruflo-kb/src/searcher/hybrid_search.py
import re
from pathlib import Path
from typing import TypedDict

class SearchResult(TypedDict):
    path: str
    title: str
    content: str
    score: float
    source: str

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
    # semantic_results = await vector_search_chunks(query_embedding, top_k)

    # 2. 关键词检索
    keyword_results = await _keyword_search(query, top_k)

    # 3. RRF 融合
    all_results = keyword_results  # 暂时只使用关键词
    return all_results[:top_k]

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
