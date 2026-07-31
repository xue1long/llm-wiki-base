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
        task_id = enqueue_task(source_str, source_type, task_hash, project_id=resolved_id)
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
        items.append({"source": rel, "source_type": SourceType.FILE, "task_hash": task_hash})

    task_ids = enqueue_batch(items, project_id=resolved_id)
    dupe_skipped = len(items) - len(task_ids)
    skipped = already_skipped + dupe_skipped + count_limited

    # Kick off initial pipeline workers (up to concurrency limit).
    # Subsequent tasks auto-advance via release_in_flight → advance().
    svc = get_default_queue_service()
    for _ in range(6):
        svc.advance(project_id=resolved_id)

    _logger.info(
        "[folder-ingest] enqueued=%d already_ingested=%d dupe_skipped=%d count_limited=%d total=%d",
        len(task_ids), already_skipped, dupe_skipped, count_limited, len(files),
    )

    result: dict = {
        "status": "batch_queued",
        "enqueued": len(task_ids),
        "skipped": skipped,
        "alreadyIngested": already_skipped,
        "duplicateSkipped": dupe_skipped,
        "taskIds": task_ids,
    }
    if count_limited > 0:
        result["countLimited"] = count_limited
    return result
