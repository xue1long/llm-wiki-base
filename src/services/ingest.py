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

from typing import Union

from ..lib.project import resolve_project
from ..queue.queue import enqueue_task
from ..types import SourceType
from ..utils.idempotency import generate_task_hash


def enqueue_source(
    project_id: str,
    source: Union[str, dict],
    folder_context: str | None = None,
) -> dict:
    """Enqueue a source for ingestion.

    Args:
        project_id: validated by resolving the project; raises
            ProjectNotFound if the project does not exist.
        source: URL string ("https://...") or {"folder": path} dict.
        folder_context: optional context string for idempotency hash.

    Returns:
        {"status": "queued" | "ignored",
         "taskId": str | None,
         "reason": None | "Duplicate"}
    """
    # Validate the project exists (raises ProjectNotFound otherwise)
    # and capture the resolved UUID so we can thread it through the queue.
    ctx, _paths = resolve_project(project_id, by_id_only=True)
    resolved_id = ctx.id

    if isinstance(source, str):
        source_str = source
        source_type = SourceType.URL if source.startswith("http") else SourceType.FILE
    else:
        source_str = source.get("folder", "")
        source_type = SourceType.FILE

    task_hash = generate_task_hash(source_type, source_str, folder_context or "")
    task_id = enqueue_task(source_str, source_type, task_hash, project_id=resolved_id)
    if not task_id:
        return {"status": "ignored", "taskId": None, "reason": "Duplicate"}
    return {"status": "queued", "taskId": task_id, "reason": None}
