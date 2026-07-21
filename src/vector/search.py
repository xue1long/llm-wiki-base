# ruflo-kb/src/vector/search.py
from .store import get_table

class ChunkSearchResult:
    def __init__(self, id: str, task_id: str, content: str, path: str, score: float):
        self.id = id
        self.task_id = task_id
        self.content = content
        self.path = path
        self.score = score

def vector_search_chunks(query_embedding: list[float], top_k: int) -> list[ChunkSearchResult]:
    """向量检索"""
    table = get_table()
    results = table.search(query_embedding).limit(top_k).to_list()

    return [
        ChunkSearchResult(
            id=r["id"],
            task_id=r["task_id"],
            content=r["content"],
            path=r["path"],
            score=1 - (r.get("_distance", 0) or 0),  # 距离转相似度
        )
        for r in results
    ]
