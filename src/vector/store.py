# ruflo-kb/src/vector/store.py
import lancedb
import pyarrow as pa
from typing import Optional

_db: Optional[lancedb.LanceDB] = None
_table: Optional[lancedb.Table] = None

def init_vector_store(db_path: str) -> None:
    """初始化 LanceDB"""
    global _db, _table
    _db = lancedb.connect(db_path)

    schema = pa.schema([
        ("id", pa.string()),
        ("task_id", pa.string()),
        ("content", pa.string()),
        ("embedding", pa.list_(pa.float32(), 1536)),
        ("path", pa.string()),
        ("updated_at", pa.int64()),
    ])

    _table = _db.create_table("chunks", schema=schema, exist_ok=True)

def get_table() -> lancedb.Table:
    if _table is None:
        raise RuntimeError("Vector store not initialized")
    return _table

def close_vector_store() -> None:
    global _db, _table
    _db = None
    _table = None
