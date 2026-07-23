# ruflo-kb/src/pipeline/librarian.py
"""Archive a note into the Knowledge store + dedup via vector similarity.

Embedding provider is sourced from ``src.llm.embedding_runtime`` (the
process-global singleton). Initialisation happens at app startup.
"""
import logging
from pathlib import Path
from datetime import datetime

from ..events.event_bus import event_bus
from ..events.events import EventName, LibrarianDonePayload, LibrarianMergedPayload
from ..llm.embedding_runtime import (
    get_embedding_provider as _runtime_get_embedding_provider,
)
from ..utils.text import chunk_markdown
from ..vector.upsert import vector_upsert_chunks
from ..vector.search import vector_search_chunks
from ..types import VectorChunk

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.95

# Public re-exports preserve the existing module attribute surface
# (callers across the codebase may import librarian.get_embedding_provider).
get_embedding_provider = _runtime_get_embedding_provider


async def archive(task_id: str, note_path: str) -> LibrarianDonePayload | LibrarianMergedPayload:
    """
    归档到 Knowledge
    包含 Pre-write Hook: 查向量库检测重复
    """
    # 1. 读取笔记内容
    note_content = Path(note_path).read_text(encoding="utf-8")

    # 2. Pre-write Hook: 查向量库相似度
    chunks = chunk_markdown(note_content)
    embeddings = []

    if chunks:
        try:
            provider = get_embedding_provider()
            # The shared runtime's protocol returns list[list[float]] — accept
            # either shape (concrete provider returns list[EmbeddingResponse])
            # and normalise below.
            embedding_results = await provider.embed(chunks)
            if embedding_results and hasattr(embedding_results[0], "embedding"):
                embeddings = [e.embedding for e in embedding_results]
            else:
                embeddings = list(embedding_results)

            # 使用第一个 chunk 的 embedding 检索相似内容
            results = vector_search_chunks(embeddings[0], top_k=1)
            if results and results[0].score > SIMILARITY_THRESHOLD:
                return await _merge_duplicates(task_id, note_path, note_content, results[0])
        except Exception as e:
            logger.warning(f"[Librarian] Embedding search failed: {e}, proceeding without dedup")
            embeddings = []

    # 3. 移动到 Knowledge
    knowledge_dir = Path("Knowledge")
    knowledge_dir.mkdir(exist_ok=True)

    file_name = Path(note_path).name
    knowledge_path = knowledge_dir / file_name

    # 读取原始 note 并写入 knowledge (保留原有内容)
    knowledge_path.write_text(note_content, encoding="utf-8")

    # 4. 写入向量
    if not embeddings:
        # 如果没有 embedding provider，使用占位符
        embeddings = [[0.0] * 1536 for _ in chunks]

    lance_chunks = [
        VectorChunk(
            id=f"{task_id}-chunk-{i}",
            task_id=task_id,
            content=chunk,
            embedding=embeddings[i] if i < len(embeddings) else [0.0] * 1536,
            path=str(knowledge_path),
            updated_at=int(datetime.now().timestamp()),
        )
        for i, chunk in enumerate(chunks)
    ]
    vector_upsert_chunks(lance_chunks)

    payload = LibrarianDonePayload(
        task_id=task_id,
        knowledge_path=str(knowledge_path),
        chunk_count=len(chunks),
    )

    event_bus.emit(EventName.LIBRARIAN_DONE, payload)
    return payload


async def _merge_duplicates(task_id: str, new_path: str, new_content: str, similar_result) -> LibrarianMergedPayload:
    """
    合并重复内容
    - 不新建文件
    - 更新旧文件的 see_also 和 last_merged
    """
    existing_path = similar_result.path
    existing_content = Path(existing_path).read_text(encoding="utf-8")

    # 添加 see_also 引用
    merged_content = existing_content + f"\n\n---\n**合并来源**: {new_path}\n**合并时间**: {datetime.now().isoformat()}\n"

    Path(existing_path).write_text(merged_content, encoding="utf-8")

    payload = LibrarianMergedPayload(
        task_id=task_id,
        existing_path=existing_path,
        merged_content=merged_content,
    )

    event_bus.emit(EventName.LIBRARIAN_MERGED, payload)
    return payload
