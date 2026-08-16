"""Ingest service — enqueue sources with idempotency.

Extracted from src/server/routes/ingest.py. Determines the SourceType
from the request shape, generates an idempotency hash, and enqueues
the task.

Audit I5: the service now resolves the project's UUID and threads it
through ``enqueue_task(project_id=...)`` so the collector/ingest chain
runs against the correct project's WikiPaths rather than the CWD-relative
default. Project identity lookup is the safe form (lookup-by-id only)
so the HTTP route behaviour matches the other 404-aware services.
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Union

from ..lib.project import resolve_project
from ..queue import enqueue_batch, enqueue_task
from ..queue.service import get_default_queue_service
from ..types import SourceType
from ..utils.idempotency import generate_task_hash
from ..wiki.features.folder_ingest import collect_files, folder_context_for

_logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".html"}



class IngestPathError(ValueError):
    """Raised when the supplied source path is outside the project root.

    Surfaced to the HTTP layer as a 400 Bad Request.
    """


def _normalize_absolute_path(
    project_root: Path, raw: str,
) -> str:
    """Convert an absolute path under project_root to a project-relative path.

    The Collector permission boundary matches relative paths only
    (raw/sources, Inbox/Processing, etc.), so absolute paths must be
    anchored inside the project before reaching the queue.

    Raises IngestPathError if the path is absolute but lives outside
    project_root — those would silently bypass the Collector boundary.
    """
    raw_posix = raw.replace("\\", "/")

    if not os.path.isabs(raw_posix):
        # Relative path — may include the project root's directory prefix
        # (e.g. "knowledge/novel-wiki/raw/sources/foo.md" when project root
        # is ".../knowledge/novel-wiki"). Use os.path functions (purely
        # computational, no filesystem access) instead of Path.resolve()
        # which can corrupt CJK characters on Windows via low-level APIs.
        raw_abs = os.path.abspath(raw_posix)
        root_abs = os.path.abspath(str(project_root).replace("\\", "/"))
        try:
            rel = os.path.relpath(raw_abs, root_abs)
        except ValueError:
            # Different drives on Windows — relpath cannot compute.
            # Still try the raw/sources fallback (below) before giving up.
            rel = raw_posix
            # Ensure we enter the fallback below.
            if not rel.startswith(".."):
                rel = ".." + rel
        if rel.startswith(".."):
            # The path resolved outside the project root. The user may have
            # omitted the "raw/sources/" prefix — ingest paths always resolve
            # relative to that directory per the Collector permission boundary
            # defined in src/permissions.py. Try to find the file under the
            # project's raw/sources/ directory as a fallback.
            sources_root = os.path.join(root_abs, "raw", "sources")
            candidate = os.path.abspath(os.path.join(sources_root, raw_posix))
            if os.path.exists(candidate):
                candidate_rel = os.path.relpath(candidate, root_abs)
                if not candidate_rel.startswith(".."):
                    # The candidate is within the project tree — prefix is correct.
                    return candidate_rel.replace("\\", "/")
            return raw_posix
        return rel.replace("\\", "/")

    # Absolute path — must live under project_root.
    # Ditto: avoid Path.resolve() in favour of os.path.abspath/relpath.
    raw_abs = os.path.abspath(raw_posix)
    root_abs = os.path.abspath(str(project_root).replace("\\", "/"))
    try:
        rel = os.path.relpath(raw_abs, root_abs)
    except ValueError:
        raise IngestPathError(
            f"absolute path {raw!r} is outside project root {str(project_root)!r};"
            " pass a project-relative path or a path under the project root"
        )
    if rel.startswith(".."):
        raise IngestPathError(
            f"absolute path {raw!r} is outside project root {str(project_root)!r};"
            " pass a project-relative path or a path under the project root"
        )
    return rel.replace("\\", "/")


def _get_ingested_paths(source_dir: Path, project_root: Path) -> set[str]:
    """Scan wiki source pages and return the set of already-ingested raw paths.

    Normalises paths to project-relative form with forward slashes so they
    can be compared against the paths produced during folder enumeration.
    Handles both absolute (legacy) and relative paths stored in frontmatter.
    """
    ingested: set[str] = set()
    if not source_dir.is_dir():
        return ingested
    for md_file in source_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            in_sources = False
            for line in text.split("\n"):
                if line.startswith("sources:"):
                    in_sources = True
                    continue
                if in_sources:
                    if line.startswith("- "):
                        path = line[2:].strip()
                        path = path.replace("\\", "/")
                        if not path or path.startswith("http"):
                            continue
                        # Normalise to project-relative form. Older pages
                        # may store absolute or partially-qualified paths;
                        # strip everything before "raw/sources/".
                        idx = path.find("raw/sources/")
                        if idx != -1:
                            path = path[idx:]
                        ingested.add(path)
                    elif line and line[0] not in (" ", "\t", "-"):
                        break
        except Exception:
            continue
    return ingested


def enqueue_source(
    project_id: str,
    source: Union[str, dict],
    folder_context: str | None = None,
    *,
    count: int | None = None,
) -> dict:
    """Enqueue a source for ingestion.

    Args:
        project_id: validated by resolving the project; raises
            ProjectNotFound if the project does not exist.
        source: URL string ("https://..."), a local file path
            (absolute or relative), or {"folder": path} dict.
            Absolute paths are anchored to the project root before
            enqueueing; paths outside the project raise IngestPathError.
        folder_context: optional context string for idempotency hash.

    Returns:
        {"status": "queued" | "ignored",
         "taskId": str | None,
         "reason": None | "Duplicate"}

    Raises:
        ProjectNotFound: project_id does not resolve.
        IngestPathError: absolute source path is outside the project root.
    """
    # Validate the project exists (raises ProjectNotFound otherwise)
    # and capture the resolved project root so we can normalize absolute
    # file paths into the relative form Collector expects.
    ctx, paths = resolve_project(project_id, by_id_only=True)
    resolved_id = ctx.id

    if isinstance(source, str):
        if source.startswith("http"):
            source_str = source
            source_type = SourceType.URL
        else:
            source_str = _normalize_absolute_path(paths.root, source)
            source_type = SourceType.FILE
        task_hash = generate_task_hash(source_type, source_str, folder_context or "", project_id=resolved_id)
        task_id = enqueue_task(source_str, source_type, task_hash, project_id=resolved_id,
                               folder_context=folder_context)
        if not task_id:
            return {"status": "ignored", "taskId": None, "reason": "Duplicate"}
        return {"status": "queued", "taskId": task_id, "reason": None}

    # Folder shape {"folder": path}: enumerate supported files and
    # enqueue each one individually. Idempotency is per-file so
    # already-ingested files are skipped; new files are queued.
    folder_raw = source.get("folder", "")
    folder_rel = _normalize_absolute_path(paths.root, folder_raw)
    folder_abs = paths.root / folder_rel
    if not folder_abs.is_dir():
        raise IngestPathError(
            f"folder {folder_rel!r} does not exist or is not a directory"
        )
    files = collect_files(folder_abs)
    supported = [f for f in files if f.suffix.lower() in _SUPPORTED_EXTENSIONS]

    # Generate batch_id for tracking
    import uuid as _uuid
    _batch_id = f"kb-batch-{_uuid.uuid4().hex[:12]}"

    # Shuffle so that when count is specified, the selection is random
    # rather than biased toward the first files in filesystem order.
    random.shuffle(supported)

    already_ingested = _get_ingested_paths(paths.wiki_sources, paths.root)

    items = []
    already_skipped = 0
    count_limited = 0
    for f in supported:
        rel = str(f.relative_to(paths.root)).replace("\\", "/")
        if rel in already_ingested:
            already_skipped += 1
            continue
        if count is not None and len(items) >= count:
            count_limited += 1
            continue
        fctx = folder_context or folder_context_for(folder_abs, f)
        task_hash = generate_task_hash(SourceType.FILE, rel, fctx, project_id=resolved_id)
        items.append({"source": rel, "source_type": SourceType.FILE, "task_hash": task_hash,
                       "folder_context": fctx})

    task_ids = enqueue_batch(items, project_id=resolved_id,
                             folder_context=folder_context, batch_id=_batch_id)
    dupe_skipped = len(items) - len(task_ids)
    skipped = already_skipped + dupe_skipped + count_limited

    # Write batch tracking state
    import json as _json
    import time as _time
    _batch_state_file = paths.root / ".index" / "batch_build_state.json"
    _batch_state: dict = {}
    if _batch_state_file.exists():
        try:
            _batch_state = _json.loads(_batch_state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    _batch_state[_batch_id] = {
        "folder": folder_rel,
        "total_files": len(supported),
        "enqueued": len(task_ids),
        "created_at": int(_time.time()),
        "status": "in_progress",
    }
    _batch_state_file.parent.mkdir(parents=True, exist_ok=True)
    _batch_state_file.write_text(_json.dumps(_batch_state, ensure_ascii=False, indent=2), encoding="utf-8")

    # Kick off initial pipeline workers (up to concurrency limit).
    # Subsequent tasks auto-advance via release_in_flight → advance().
    svc = get_default_queue_service()
    for _ in range(6):
        svc.advance(project_id=resolved_id)

    _logger.info(
        "[folder-ingest] enqueued=%d already_ingested=%d dupe_skipped=%d count_limited=%d total=%d batch=%s",
        len(task_ids), already_skipped, dupe_skipped, count_limited, len(files), _batch_id,
    )

    result: dict = {
        "status": "batch_queued",
        "enqueued": len(task_ids),
        "skipped": skipped,
        "alreadyIngested": already_skipped,
        "duplicateSkipped": dupe_skipped,
        "taskIds": task_ids,
        "batchId": _batch_id,
    }
    if count_limited > 0:
        result["countLimited"] = count_limited
    return result


def run_ingest_pipeline(paths, source_path, source_text, provider, task_id="svc"):
    """Run the full ingest pipeline synchronously (async wrapper)."""
    import asyncio
    from ..pipeline.ingest import run_ingest
    return asyncio.run(run_ingest(paths, source_path, source_text, provider, task_id=task_id))


def _find_source_page_by_raw_path(wiki_sources_dir: Path, raw_path: str) -> str | None:
    """Find the source page ID whose frontmatter ``sources`` contains ``raw_path``.

    Scans every ``.md`` file under *wiki_sources_dir*, parses the YAML
    frontmatter, and returns the first page whose ``sources:`` list includes
    *raw_path* (normalised to forward slashes).  Returns ``None`` when no
    match is found.
    """
    raw_path = raw_path.replace("\\", "/")
    if not wiki_sources_dir.is_dir():
        return None
    for md_file in wiki_sources_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            lines = text.split("\n")
            # Fast path: skip files that don't mention the raw path at all
            if raw_path not in text:
                continue
            in_sources = False
            page_id = None
            for line in lines:
                if line.startswith("id:"):
                    page_id = line[3:].strip()
                if line.startswith("sources:"):
                    in_sources = True
                    continue
                if in_sources:
                    if line.startswith("- "):
                        val = line[2:].strip().replace("\\", "/")
                        if val == raw_path:
                            return page_id
                    elif line and line[0] not in (" ", "\t", "-"):
                        break
        except Exception:
            continue
    return None


def probe_source_page(paths, raw_path: str) -> str | None:
    """Return the source page ID for *raw_path*, or ``None`` (never raises).

    Phase 4 per-raw branch (C2): the executor probes the wiki before
    deciding reingest vs first ingest.  Returns ``None`` when the raw was
    never ingested (or its source page was cleaned up) — the caller then
    falls to the first-ingest branch.
    """
    try:
        return _find_source_page_by_raw_path(paths.wiki_sources, raw_path)
    except Exception:
        return None


def reingest_source(project_id: str, raw_path: str) -> dict:
    """Re-ingest a previously processed raw source file.

    Workflow:
        1. Resolve project and validate it exists.
        2. Find the wiki source page whose frontmatter ``sources`` contains
           *raw_path*.
        3. Call ``cascade_delete`` to remove all wiki pages generated from
           this source.
        4. Delete all LanceDB vectors whose ``path`` column matches the
           raw source path.
        5. Re-enqueue the source for ingestion via ``enqueue_source``.

    Args:
        project_id: validated project UUID.
        raw_path: project-relative path to the raw source file, e.g.
            ``"raw/sources/01_新手入门/0_小说人物辅助设定.md"``.

    Returns:
        The same shape as ``enqueue_source``: ``{"status", "taskId", ...}``
        with an extra ``"cleaned"`` field summarising what was deleted.

    Raises:
        ProjectNotFoundError: project_id does not resolve.
        ValueError: no wiki source page found for *raw_path* (i.e. the
            file was never ingested, or the wiki sources have been cleaned
            manually).
    """
    from ..lib.project import resolve_project
    from ..wiki.features.cascade_delete import cascade_delete
    from ..vector.store import delete_by_source, init_vector_store_for_paths

    ctx, paths = resolve_project(project_id, by_id_only=True)

    # Step 2 — find the source page
    source_id = _find_source_page_by_raw_path(paths.wiki_sources, raw_path)
    if source_id is None:
        raise ValueError(
            f"No wiki source page found for {raw_path!r}; "
            "the file may not have been ingested yet."
        )

    # Step 3 — cascade delete wiki pages
    cascade_result = cascade_delete(paths, source_id)

    # Step 4 — delete vectors
    init_vector_store_for_paths(paths)
    deleted_vectors = delete_by_source(paths, raw_path)

    _logger.info(
        "[reingest] source=%s source_id=%s deleted_vectors=%d updated=%s deleted=%s",
        raw_path, source_id, deleted_vectors,
        cascade_result.get("updated_pages", []),
        cascade_result.get("deleted_pages", []),
    )

    # Step 5 — re-enqueue
    enqueue_result = enqueue_source(project_id, raw_path)

    # Merge results
    enqueue_result["cleaned"] = {
        "source_id": source_id,
        "deleted_pages": cascade_result.get("deleted_pages", []),
        "updated_pages": cascade_result.get("updated_pages", []),
        "deleted_vectors": deleted_vectors,
    }
    return enqueue_result


async def reingest_source_direct(
    paths,
    raw_path: str,
    provider,
    *,
    batch_key: str,
    task_id: str = "reingest",
    resume_from_pending_deletion: bool = False,
) -> dict:
    """Phase 4 直跑重建分支（C2 P0 加固，plan guidance #3/#4）——不经队列。

    直跑路径是 Phase 4 唯一执行路径（B6/C2 定死）：脚本进程内直接调用
    ``run_ingest`` 重建，绝不 ``enqueue_source``（队列降级只读）。

    每 raw 分支：
    - **有 source 页** → cascade_delete 旧产出 + 删向量 + run_ingest 重建；
    - **无 source 页** → 直接 run_ingest 首次摄入（首摄分支，不抛错）；
    - cascade 时源页已被并发删除（FileNotFoundError）→ 降级首摄而非 failed。

    补偿状态（plan guidance #4）：重建路径顺序 = 记 ``pending_deletion`` →
    cascade_delete → 记 ``done``。崩溃在删除后、重建前 → 续跑时对
    ``pending_deletion`` 文件重跑重建（``resume_from_pending_deletion=True``
    时直接走首摄式重建，因旧 source 页已删）。禁止"先删后建"裸窗口。

    Returns::

        {"status": "done", "branch": "reingest"|"first_ingest",
         "cleaned": {...}, "note": "..."}
    """
    from .batch_state import set_raw_status
    from ..pipeline.ingest import run_ingest
    from ..wiki.features.cascade_delete import cascade_delete
    from ..vector.store import delete_by_source, init_vector_store_for_paths

    source_id = probe_source_page(paths, raw_path)
    branch = "reingest" if source_id is not None else "first_ingest"
    note = ""
    cascade_result: dict = {}

    if source_id is not None:
        # 重建调度成功（探到旧产出）→ 先记 pending_deletion，再删。
        set_raw_status(paths, batch_key, raw_path, "pending_deletion",
                       source_id=source_id)
        try:
            cascade_result = cascade_delete(paths, source_id)
        except FileNotFoundError:
            # 探到源页后、cascade 前被并发删除（或索引残留）→ 首摄分支。
            branch = "first_ingest"
            note = "deleted_between_probe_and_cascade"
            cascade_result = {}
        else:
            init_vector_store_for_paths(paths)
            deleted_vectors = delete_by_source(paths, raw_path)
            cascade_result["deleted_vectors"] = deleted_vectors
    else:
        if resume_from_pending_deletion:
            note = "resumed_from_pending_deletion"

    # 直跑重建：run_ingest（generate + commit 一体），不经队列。
    src = paths.root / raw_path
    text = src.read_text(encoding="utf-8", errors="replace")
    pages = await run_ingest(
        paths=paths, source_path=Path(raw_path), source_text=text,
        provider=provider, task_id=task_id,
    )

    set_raw_status(paths, batch_key, raw_path, "done", branch=branch)
    return {
        "status": "done",
        "branch": branch,
        "cleaned": {
            "source_id": source_id,
            "deleted_pages": cascade_result.get("deleted_pages", []),
            "updated_pages": cascade_result.get("updated_pages", []),
            "deleted_vectors": cascade_result.get("deleted_vectors", 0),
        },
        "note": note,
        "pages": len(pages),
    }


def delete_source(project_id: str, raw_path: str) -> dict:
    """Delete all compiled wiki information for a raw source — no re-ingest.

    Removes the wiki source page (and cascades to any entity/concept/
    synthesis pages that reference its sources) plus all LanceDB vectors
    whose ``path`` column matches *raw_path*. Unlike ``reingest_source``,
    it does NOT re-enqueue the source; the raw file is left untouched.

    Args:
        project_id: validated project UUID.
        raw_path: project-relative path to the raw source file, e.g.
            ``"raw/sources/01_新手入门/0_小说人物辅助设定.md"``.

    Returns:
        {"status": "deleted", "source_id", "deleted_pages",
         "updated_pages", "deleted_vectors"}.

    Raises:
        ProjectNotFoundError: project_id does not resolve.
        ValueError: no wiki source page found for *raw_path* (i.e. the
            file was never ingested, or the wiki sources have been cleaned
            manually).
    """
    from ..lib.project import resolve_project
    from ..wiki.features.cascade_delete import cascade_delete
    from ..vector.store import delete_by_source, init_vector_store_for_paths

    ctx, paths = resolve_project(project_id, by_id_only=True)

    source_id = _find_source_page_by_raw_path(paths.wiki_sources, raw_path)
    if source_id is None:
        raise ValueError(
            f"No wiki source page found for {raw_path!r}; "
            "the file may not have been ingested yet."
        )

    cascade_result = cascade_delete(paths, source_id)

    init_vector_store_for_paths(paths)
    deleted_vectors = delete_by_source(paths, raw_path)

    _logger.info(
        "[delete_source] source=%s source_id=%s deleted_vectors=%d updated=%s deleted=%s",
        raw_path, source_id, deleted_vectors,
        cascade_result.get("updated_pages", []),
        cascade_result.get("deleted_pages", []),
    )

    return {
        "status": "deleted",
        "source_id": source_id,
        "deleted_pages": cascade_result.get("deleted_pages", []),
        "updated_pages": cascade_result.get("updated_pages", []),
        "deleted_vectors": deleted_vectors,
    }
