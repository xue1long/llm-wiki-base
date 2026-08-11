# ruflo-kb/src/pipeline/librarian.py
"""Archive a note into the Knowledge store + dedup via vector similarity.

Embedding provider is sourced from ``src.llm.embedding_runtime`` (the
process-global singleton). Initialisation happens at app startup.

The ``paths: WikiPaths`` parameter (required since the wiki-v2 split)
anchors all filesystem writes inside ``paths.knowledge_dir`` (alias for
``<root>/wiki``). Persisted paths (vector ``path`` column, ``**合并来源**``
provenance) are stored PROJECT-RELATIVE so the KB survives device moves.

``_merge_duplicates`` resolves a stored existing_path against the current
root via ``resolve_stored_path``; foreign / stale / missing paths make it
return ``None`` so ``archive()`` falls through to a normal archive (which
overwrites the stale vector row with a project-relative path — self-heal).
This closes the path-injection vector (no writes outside root) without
crashing on a different device's absolute root.
"""
import logging
from pathlib import Path

from ..utils.path import normalize_source_path, resolve_stored_path, safe_resolve
from datetime import datetime

from ..events.event_bus import event_bus
from ..events.events import EventName, LibrarianDonePayload, LibrarianMergedPayload
from ..llm.embedding_runtime import (
    get_embedding_provider as _runtime_get_embedding_provider,
)
from ..lib.write_hooks import safe_write
from ..utils.text import chunk_markdown
from ..vector.upsert import vector_upsert_chunks
from ..vector.search import vector_search_chunks
from ..types import VectorChunk
from ..wiki.core.paths import WikiPaths

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.95

# Public re-exports preserve the existing module attribute surface
# (callers across the codebase may import librarian.get_embedding_provider).
get_embedding_provider = _runtime_get_embedding_provider


async def archive(
    task_id: str,
    note_path: str,
    paths: WikiPaths,
) -> LibrarianDonePayload | LibrarianMergedPayload:
    """
    归档到 Knowledge
    包含 Pre-write Hook: 查向量库检测重复

    Parameters
    ----------
    task_id:
        Identifier of the task being archived.
    note_path:
        Path to the source note (typically inside ``paths.wiki_sources``
        or similar typed subdirectory).
    paths:
        WikiPaths for the project. The archive target is anchored inside
        ``paths.knowledge_dir`` (alias for ``<root>/wiki`` in v2).
    """
    # 1. 读取笔记内容
    note_content = Path(note_path).read_text(encoding="utf-8")
    if not safe_resolve(note_path).is_relative_to(safe_resolve(paths.root)):
        logger.warning(
            "[Librarian] note_path %r is outside the project root — its vector path "
            "will be stored absolute (normalize_source_path falls back)",
            note_path,
        )

    # 2. Pre-write Hook: 查向量库相似度
    chunks = chunk_markdown(note_content)
    embeddings = []

    similar_result = None
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
            results = vector_search_chunks(embeddings[0], top_k=1, project_paths=paths)
            if results and results[0].score > SIMILARITY_THRESHOLD:
                similar_result = results[0]
        except Exception as e:
            logger.warning(f"[Librarian] Embedding search failed: {e}, proceeding without dedup")
            embeddings = []

    # Foreign/stale existing_path (e.g. a different device's absolute root)
    # makes _merge_duplicates return None — fall through to a normal archive so
    # the stale vector row is overwritten with a project-relative path.
    if similar_result is not None:
        merged = await _merge_duplicates(
            task_id, note_path, note_content, similar_result, paths
        )
        if merged is not None:
            return merged

    # 3. 写入向量 — 直接引用原始笔记路径，不再复制到 knowledge_dir。
    # Audit I6 / M2: if the embedding provider is missing or the embed call
    # failed, DO NOT write zero vectors (they poison the index).
    if not embeddings:
        raise RuntimeError(
            f"[Librarian] No embeddings produced for {task_id}: "
            f"embedding provider may be unconfigured or the embed call failed. "
            f"Refusing to write zero vectors to the index."
        )

    lance_chunks = [
        VectorChunk(
            id=f"{task_id}-chunk-{i}",
            task_id=task_id,
            content=chunk,
            embedding=embeddings[i] if i < len(embeddings) else [0.0] * 384,
            path=normalize_source_path(str(note_path), paths.root),
            updated_at=int(datetime.now().timestamp()),
        )
        for i, chunk in enumerate(chunks)
    ]
    vector_upsert_chunks(lance_chunks)

    payload = LibrarianDonePayload(
        task_id=task_id,
        knowledge_path=normalize_source_path(str(note_path), paths.root),
        chunk_count=len(chunks),
    )

    event_bus.emit(EventName.LIBRARIAN_DONE, payload)
    return payload


async def _merge_duplicates(
    task_id: str,
    new_path: str,
    new_content: str,
    similar_result,
    paths: WikiPaths,
) -> LibrarianMergedPayload:
    """
    合并重复内容
    - 不新建文件
    - 更新旧文件的 see_also 和 last_merged

    ``similar_result.path`` is resolved against the current project root. A
    foreign / stale / missing path (e.g. a different device's absolute root,
    or ``..`` traversal) makes this return ``None`` instead of merging, so
    ``archive()`` falls through to a normal archive. This prevents the vector
    store from redirecting writes outside root without crashing the archive.
    """
    existing_path = similar_result.path
    existing_resolved = resolve_stored_path(existing_path, paths.root)
    if existing_resolved is None:
        logger.warning(
            "[Librarian] Skipping merge: existing_path %r is foreign/stale (outside project root)",
            existing_path,
        )
        return None
    if existing_resolved == safe_resolve(new_path):
        # Self-match is degenerate dedup (a page "merging into itself").
        # Skipping it keeps merged-target notes' digests stable so they are not
        # re-embedded forever (appending self-provenance changed content each
        # run -> 284 files accumulated endless **合并来源** blocks).
        logger.warning(
            "[Librarian] Skipping merge: existing_path %r is the note itself (self-match)",
            existing_path,
        )
        return None

    knowledge_resolved = safe_resolve(paths.knowledge_dir)
    # is_relative_to (3.9+) returns True/False; older versions raise
    # ValueError. Accept both shapes via try/except, then check the result.
    try:
        inside = existing_resolved.is_relative_to(knowledge_resolved)
    except (ValueError, AttributeError):
        inside = False
    if not inside:
        logger.warning(
            "[Librarian] Skipping merge: existing_path %r outside knowledge_dir", existing_path
        )
        return None
    if not existing_resolved.is_file():
        logger.warning(
            "[Librarian] Skipping merge: existing_path %r is not a regular file", existing_path
        )
        return None

    existing_content = existing_resolved.read_text(encoding="utf-8")

    # 添加 see_also 引用(来源存项目相对路径,跨设备稳定)
    merged_content = (
        existing_content
        + f"\n\n---\n**合并来源**: {normalize_source_path(str(new_path), paths.root)}\n"
        + f"**合并时间**: {datetime.now().isoformat()}\n"
    )

    # Audit I6: route through safe_write so merge writes are atomic and
    # AtomicContext-aware.
    safe_write(existing_resolved, merged_content)

    payload = LibrarianMergedPayload(
        task_id=task_id,
        existing_path=str(existing_resolved),
        merged_content=merged_content,
    )

    event_bus.emit(EventName.LIBRARIAN_MERGED, payload)
    return payload
