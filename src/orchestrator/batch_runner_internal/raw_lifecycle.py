"""Raw lifecycle helpers used by the batch runner facade."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.services.batch_state import set_raw_status
from src.wiki.core.paths import WikiPaths

from .hooks import _crash_at

_logger = logging.getLogger("batch_runner")


def _git_snapshot(paths: WikiPaths) -> str | None:
    """记录当前 git HEAD（每批前快照，guidance #13）。非 git 仓库返回 None。"""
    try:
        r = subprocess.run(
            ["git", "-C", str(paths.root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _is_immutable_source(paths: WikiPaths, raw_rel: str) -> bool:
    """is_immutable 存量 source 页 → True（摄入前跳过，guidance #13）。"""
    from src.services.ingest import probe_source_page
    from src.wiki.storage.page_writer import read_page, page_path_for
    from src.wiki.core.types import PageType

    source_id = probe_source_page(paths, raw_rel)
    if source_id is None:
        return False
    try:
        page = read_page(page_path_for(paths, PageType.SOURCE, source_id))
        return bool(getattr(page, "is_immutable", False))
    except Exception:
        return False


async def _generate_raw(paths, provider, raw_rel, batch_no) -> tuple[list, list, dict]:
    """Phase 1：生成单 raw 页面（dry，零磁盘写）。返回 (pages, extras, meta)。"""
    from src.pipeline.ingest import generate_ingest

    src = paths.root / raw_rel
    text = src.read_text(encoding="utf-8", errors="replace")
    task_id = f"b{batch_no}-{Path(raw_rel).stem[:30]}"
    return await generate_ingest(
        paths=paths, source_path=Path(raw_rel), source_text=text,
        provider=provider, task_id=task_id,
    )


def _ensure_rebuild_clean(paths, source_id, raw_rel, batch_key) -> str:
    """Mark deletion before cascading; concurrent deletion degrades safely."""
    from src.wiki.features.cascade_delete import cascade_delete

    set_raw_status(paths, batch_key, raw_rel, "pending_deletion",
                   source_id=source_id)
    try:
        cascade_delete(paths, source_id)
    except FileNotFoundError:
        return "first_ingest"
    return "reingest"


def _clear_stale_vectors(paths, raw_rel) -> None:
    """Delete old vectors idempotently after page cascade or first ingest."""
    from src.vector.store import delete_by_source, init_vector_store_for_paths

    init_vector_store_for_paths(paths)
    delete_by_source(paths, raw_rel)


async def _commit_ingest(paths, raw_rel, pages, extras, task_id,
                         meta: dict | None = None,
                         expected_page_hashes: dict | None = None) -> None:
    from src.pipeline.ingest import commit_ingest

    missing_slugs = (meta or {}).get("missing_slugs")
    await commit_ingest(paths, Path(raw_rel), pages, extras, task_id=task_id,
                        missing_slugs=missing_slugs,
                        readiness_audit=(meta or {}).get("readiness_audit"),
                        expected_page_hashes=expected_page_hashes)


async def _commit_raw(paths, raw_rel, pages, extras, batch_key, task_id,
                      meta: dict | None = None,
                      expected_page_hashes: dict | None = None) -> str:
    """Phase 3 coordinator: probe → clean → commit → mark done."""
    from src.services.ingest import probe_source_page

    source_id = probe_source_page(paths, raw_rel)
    branch = "first_ingest"
    if source_id is not None:
        branch = _ensure_rebuild_clean(paths, source_id, raw_rel, batch_key)
    _clear_stale_vectors(paths, raw_rel)
    _crash_at("cascade")
    await _commit_ingest(paths, raw_rel, pages, extras, task_id,
                          meta=meta, expected_page_hashes=expected_page_hashes)
    set_raw_status(paths, batch_key, raw_rel, "done", branch=branch)
    return branch


async def _upsert_batch_vectors(paths, pages) -> int:
    """为批内已提交页面切块 + embedding + upsert。"""
    from src.utils.text import chunk_markdown
    from src.llm.embedding_runtime import get_embedding_provider
    from src.vector.store import init_vector_store_for_paths
    from src.vector.upsert import vector_upsert_chunks
    from src.types import VectorChunk
    from src.utils.path import normalize_source_path
    from datetime import timezone, datetime

    init_vector_store_for_paths(paths)
    provider = get_embedding_provider()
    total = 0
    for p in pages:
        content = (p.body or "").strip()
        if not content:
            continue
        chunks = chunk_markdown(content)
        if not chunks:
            continue
        embedding_results = await provider.embed(chunks)
        if embedding_results and hasattr(embedding_results[0], "embedding"):
            embeddings = [e.embedding for e in embedding_results]
        else:
            embeddings = list(embedding_results)
        if not embeddings or len(embeddings) != len(chunks):
            continue
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        lance_chunks = [
            VectorChunk(
                id=f"{p.id}-chunk-{i}",
                task_id=p.id,
                content=chunk,
                embedding=embeddings[i],
                path=normalize_source_path(p.id, paths.root),
                updated_at=now,
            )
            for i, chunk in enumerate(chunks)
        ]
        vector_upsert_chunks(lance_chunks)
        total += len(lance_chunks)
    return total
