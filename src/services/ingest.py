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

import os
from pathlib import Path
from typing import Union

from ..lib.project import resolve_project
from ..queue import enqueue_task
from ..types import SourceType
from ..utils.idempotency import generate_task_hash


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
    # Normalise to forward slashes — the Collector boundary check uses
    # PurePosixPath ancestry (per C-13 fix), so backslashes would not
    # match the documented allowlist (raw/sources, Inbox/Processing).
    raw_posix = raw.replace("\\", "/")
    root_posix = str(project_root).replace("\\", "/")
    # Use os.path.isabs as the absolute-path test (matches Path.is_absolute
    # for both POSIX and Windows drive-relative paths; documented as the
    # boundary check used by the Collector permission allowlist).
    if not os.path.isabs(raw_posix):
        return raw_posix
    # M2: resolve both paths to canonicalise symlinks before
    # relative_to. Pure-string relative_to would raise ValueError if
    # the caller supplies the real path but the registry holds the
    # symlinked root (or vice versa).
    try:
        rel = Path(raw_posix).resolve().relative_to(Path(root_posix).resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        raise IngestPathError(
            f"absolute path {raw!r} is outside project root {str(project_root)!r};"
            " pass a project-relative path or a path under the project root"
        )


def enqueue_source(
    project_id: str,
    source: Union[str, dict],
    folder_context: str | None = None,
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
    else:
        # Folder shape {"folder": path}: pass through verbatim; the
        # Collector raises Unsupported file type for a directory path
        # (folder ingestion is not wired up — see CLAUDE.md note).
        source_str = source.get("folder", "")
        source_type = SourceType.FILE

    task_hash = generate_task_hash(source_type, source_str, folder_context or "")
    task_id = enqueue_task(source_str, source_type, task_hash, project_id=resolved_id)
    if not task_id:
        return {"status": "ignored", "taskId": None, "reason": "Duplicate"}
    return {"status": "queued", "taskId": task_id, "reason": None}
