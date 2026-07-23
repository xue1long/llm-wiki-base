# ruflo-kb/src/vector/__init__.py
from .store import (
    init_vector_store,
    init_vector_store_for_paths,
    get_table,
    close_vector_store,
    __reset_for_testing,
    current_project_paths,
)
from .search import vector_search_chunks, ChunkSearchResult
from .upsert import vector_upsert_chunks, vector_delete_page, vector_clear_chunks

__all__ = [
    "init_vector_store",
    "init_vector_store_for_paths",
    "get_table",
    "close_vector_store",
    "current_project_paths",
    "vector_search_chunks",
    "vector_upsert_chunks",
    "vector_delete_page",
    "vector_clear_chunks",
    "ChunkSearchResult",
]
