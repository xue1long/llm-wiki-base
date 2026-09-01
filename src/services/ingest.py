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

import yaml

from ..lib.project import resolve_project
from ..queue import enqueue_batch, enqueue_task
from ..queue.service import get_default_queue_service
from ..types import SourceType
from ..utils.idempotency import generate_task_hash
from ..wiki.features.folder_ingest import collect_files, folder_context_for

_logger = logging.getLogger(__name__)

# Supported file extensions for raw ingestion (audit PR-2 Task E).
# Mirrors src/pipeline/collector.collect() accept-list; ``.doc`` is
# intentionally excluded because ``extract_office_text`` raises
# ``UnsupportedFormat`` for legacy binary OLE Compound File format
# (the design calls for users to convert to ``.docx`` first).
_SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".html", ".htm"}



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


def _normalize_raw_path(path: str) -> str:
    """Normalise a raw source path to project-relative form with forward slashes.

    Strips anything before ``raw/sources/`` so legacy pages that store
    absolute (D:\\...) or partially-qualified project-relative paths
    (``knowledge/novel-wiki/raw/sources/foo.md``) collapse to the same
    canonical key. Empty strings and URLs are returned unchanged.
    """
    if not path:
        return ""
    path = path.replace("\\", "/")
    if path.startswith("http"):
        return path
    idx = path.find("raw/sources/")
    if idx != -1:
        return path[idx:]
    return path


def _extract_frontmatter(text: str) -> dict:
    """Parse the YAML frontmatter (between ``---`` fences) from a markdown file.

    Returns ``{}`` when the file is missing a frontmatter block or the YAML
    fails to parse. The parser intentionally uses ``yaml.safe_load`` so we
    handle every YAML-supported representation (block list, flow list,
    single quoted, double quoted, multiline literals, etc.) without
    bespoke logic.
    """
    if not text.startswith("---"):
        return {}
    # Find the closing fence. Following the same convention as
    # src/wiki/storage/page_writer.py::read_page.
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fm_text = text[4:end]
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}


def _page_sources_from_text(text: str) -> list[str]:
    """Return the ``sources:`` list of a markdown file (project-relative,
    normalised). Empty list on missing / malformed frontmatter.

    Replaces the previous line-scanner which silently broke on:
      * inline flow style: ``sources: [raw/a.md, raw/b.md]``
      * quoted entries: ``sources:\n  - "raw/a.md"``
    Both shapes are now parsed by ``yaml.safe_load``.
    """
    fm = _extract_frontmatter(text)
    raw = fm.get("sources", [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        normalized = _normalize_raw_path(item)
        if not normalized or normalized.startswith("http"):
            continue
        out.append(normalized)
    return out


def _page_id_from_text(text: str) -> str | None:
    """Read the ``id:`` frontmatter field from a markdown file.

    Returns ``None`` when the field is absent. Use the file's stem as a
    fallback if the frontmatter block is missing entirely.
    """
    fm = _extract_frontmatter(text)
    pid = fm.get("id")
    if isinstance(pid, str) and pid.strip():
        return pid.strip()
    return None


def _get_ingested_paths(source_dir: Path, project_root: Path) -> set[str]:
    """Scan wiki source pages and return the set of already-ingested raw paths.

    Normalises paths to project-relative form with forward slashes so they
    can be compared against the paths produced during folder enumeration.
    Handles both absolute (legacy) and relative paths stored in frontmatter
    of every YAML-supported shape (block list, inline flow, quoted entries).
    """
    ingested: set[str] = set()
    if not source_dir.is_dir():
        return ingested
    for md_file in source_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            ingested.update(_page_sources_from_text(text))
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
            # Idempotency against an existing wiki source page (PR-2
            # Task D): the folder ingest branch already consults
            # ``_get_ingested_paths`` before enqueuing. The single-file
            # branch used to skip this check entirely — a re-submitted
            # URL hit the queue, the queue's on-disk dedup saw only a
            # stale APPROVED task (or nothing for fully completed runs),
            # removed that record, and let a fresh task through.
            #
            # URLs are recorded verbatim on the wiki page's
            # ``sources:`` list (collector keeps the URL as raw_path for
            # URLs), so we match against the raw YAML frontmatter list
            # rather than the normalised raw path.
            if _find_source_page_by_url(paths.wiki_sources, source_str):
                return {
                    "status": "ignored",
                    "taskId": None,
                    "reason": "AlreadyIngested",
                }
        else:
            source_str = _normalize_absolute_path(paths.root, source)
            source_type = SourceType.FILE
            # Same dedup mirror for the file branch.
            if _find_source_page_by_raw_path(paths.wiki_sources, source_str):
                return {
                    "status": "ignored",
                    "taskId": None,
                    "reason": "AlreadyIngested",
                }
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

    # Write batch tracking state — 统一 schema + 文件锁（H① 三写者契约）：
    # 必须经 batch_state.update_batch_state（持锁读-改-写 + os.replace 原子写
    # + schema_version），否则与 Phase 4 executor 的 set_raw_status 并发即
    # 丢失更新（review C1）。
    import time as _time
    from .batch_state import update_batch_state
    update_batch_state(paths, lambda st: (
        st.__setitem__(_batch_id, {
            "folder": folder_rel,
            "total_files": len(supported),
            "enqueued": len(task_ids),
            "created_at": int(_time.time()),
            "status": "in_progress",
        }),
        st)[1])

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

    The YAML parser (audit PR-2) handles every representation uniformly —
    block list, inline flow, quoted entries — instead of the prior line
    scanner that silently missed inline flows.
    """
    target = _normalize_raw_path(raw_path)
    if not target or target.startswith("http"):
        return None
    if not wiki_sources_dir.is_dir():
        return None
    for md_file in wiki_sources_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            # Cheap pre-check: skip the YAML parse cost for files that
            # do not mention the target string at all.
            if target not in text.replace("\\", "/"):
                continue
            sources = _page_sources_from_text(text)
            if target in sources:
                return _page_id_from_text(text)
        except Exception:
            continue
    return None


def _find_source_page_by_url(wiki_sources_dir: Path, url: str) -> str | None:
    """Find the source page ID whose frontmatter ``sources`` contains ``url``.

    URL counterpart of ``_find_source_page_by_raw_path``. The collector
    stores the URL verbatim on URL-sourced wiki pages, so we match the raw
    YAML list value directly (no project-root normalisation). Returns
    ``None`` when no match is found.
    """
    if not url or not url.startswith("http"):
        return None
    if not wiki_sources_dir.is_dir():
        return None
    for md_file in wiki_sources_dir.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            if url not in text:
                continue
            fm = _extract_frontmatter(text)
            sources = fm.get("sources", [])
            if not isinstance(sources, list):
                continue
            for item in sources:
                if isinstance(item, str) and item == url:
                    return _page_id_from_text(text)
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
    on_stage=None,
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

    ``on_stage``（executor 崩溃注入钩子，可选）：在每个可崩溃阶段回调
    ``on_stage("generate"|"cascade"|"commit")`` —— 直跑执行器用它挂
    kill -9 注入点，普通调用方省略。

    Returns::

        {"status": "done", "branch": "reingest"|"first_ingest",
         "cleaned": {...}, "note": "..."}
    """
    from .batch_state import set_raw_status
    from ..pipeline.ingest import run_ingest
    from ..wiki.features.cascade_delete import cascade_delete
    from ..vector.store import delete_by_source, init_vector_store_for_paths

    if on_stage is not None:
        on_stage("generate")

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
        if on_stage is not None:
            on_stage("cascade")
    else:
        if resume_from_pending_deletion:
            note = "resumed_from_pending_deletion"
            # I1（review）：崩溃发生在 cascade_delete 与 delete_by_source 之间时，
            # 续跑 probe 返回 None → 走此分支 —— 旧向量必须仍被清理（幂等，
            # 无残留时删 0 行），否则重建页新 id 不覆盖旧行，搜索命中陈旧 chunk。
            init_vector_store_for_paths(paths)
            delete_by_source(paths, raw_path)

    # 直跑重建：run_ingest（generate + commit 一体），不经队列。
    # I2（review）：重建段必须有失败契约——失败先落状态再抛，禁止
    # pending_deletion 悬空（否则续跑必然再次失败 → 无限重试）。
    try:
        src = paths.root / raw_path
        text = src.read_text(encoding="utf-8", errors="replace")
        pages = await run_ingest(
            paths=paths, source_path=Path(raw_path), source_text=text,
            provider=provider, task_id=task_id,
        )
    except FileNotFoundError:
        # raw 文件本身缺失 → 非瞬态：permanent_failed（不重投）。
        set_raw_status(paths, batch_key, raw_path, "permanent_failed",
                       last_error=f"raw file missing: {raw_path}")
        raise
    except Exception as exc:
        set_raw_status(paths, batch_key, raw_path, "failed", last_error=str(exc))
        raise

    set_raw_status(paths, batch_key, raw_path, "done", branch=branch)
    if on_stage is not None:
        on_stage("commit")
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
