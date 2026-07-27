# ruflo-kb/src/vector/search.py
from typing import TYPE_CHECKING

from .store import get_table

if TYPE_CHECKING:
    from ..wiki.core.paths import WikiPaths

class ChunkSearchResult:
    def __init__(self, id: str, task_id: str, content: str, path: str, score: float):
        self.id = id
        self.task_id = task_id
        self.content = content
        self.path = path
        self.score = score

def vector_search_chunks(
    query_embedding: list[float],
    top_k: int,
    project_paths: "WikiPaths | None" = None,
) -> list[ChunkSearchResult]:
    """向量检索.

    Audit I3: pass ``project_paths`` so multi-project search does not
    cross-pollute. When ``None``, falls back to the process-global
    current project (legacy CLI / test compatibility).
    """
    table = get_table(project_paths)
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