# ruflo-kb/src/vector/upsert.py
from .store import get_table
from ..types import VectorChunk

def vector_upsert_chunks(chunks: list[VectorChunk]) -> None:
    """批量写入向量"""
    table = get_table()
    data = [
        {
            "id": c.id,
            "task_id": c.task_id,
            "content": c.content,
            "embedding": c.embedding,
            "path": c.path,
            "updated_at": c.updated_at,
        }
        for c in chunks
    ]
    table.add(data)

def vector_delete_page(task_id: str) -> None:
    """删除指定 task 的所有向量"""
    table = get_table()
    table.delete(f"task_id = '{task_id}'")

def vector_clear_chunks() -> None:
    """清空所有向量"""
    table = get_table()
    table.delete("true")
