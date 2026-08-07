# src/server/routes/ingest.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Union
from ...project.context import ProjectNotFoundError
from ...services import ingest as ingest_service
from ...services.ingest import IngestPathError
from ..ingest_tracker import get_task, list_tasks

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: Union[str, dict]   # URL or {"folder": path}
    folderContext: str | None = None
    count: int | None = None   # max files to enqueue (folder only)


class ReingestRequest(BaseModel):
    source_path: str   # project-relative raw path, e.g. "raw/sources/foo.md"


@router.post("/projects/{project_id}/ingest")
async def ingest(project_id: str, body: IngestRequest):
    """Enqueue a URL or folder path for ingestion."""
    try:
        return ingest_service.enqueue_source(project_id, body.source, body.folderContext, count=body.count)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except IngestPathError as e:
        # Per services/ingest.IngestPathError docstring: the service
        # raises this for absolute paths outside the project root.
        # Surface as HTTP 400 (client error) rather than the default
        # 500 the unhandled exception would produce.
        raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/reingest")
async def reingest(project_id: str, body: ReingestRequest):
    """Delete all wiki pages and vectors for a source, then re-ingest it.

    Body:
        ``source_path``: project-relative path to the raw source file,
        e.g. ``"raw/sources/01_新手入门/0_小说人物辅助设定.md"``.

    Returns the same shape as ``POST /ingest`` with an extra ``cleaned``
    field summarising what was deleted.
    """
    try:
        return ingest_service.reingest_source(project_id, body.source_path)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except IngestPathError as e:
        raise HTTPException(400, str(e))


@router.get("/projects/{project_id}/ingest/status/{task_id}")
async def ingest_status(project_id: str, task_id: str):
    """Return the lifecycle record for a single ingest task.

    Spec: FRONTEND_DESIGN.md §14.1. The frontend polls this after submitting
    an ingest to render a progress indicator.

    Returns 404 if the task_id is not tracked. Note that idempotency hits
    (status="ignored" returned by POST /ingest) are not tracked because the
    queue refuses to enqueue them in the first place — the frontend should
    treat such a response as terminal without polling.
    """
    rec = get_task(task_id)
    if rec is None:
        raise HTTPException(404, f"task {task_id!r} not found (or already pruned)")
    # Sanity-check project ownership (do not leak other projects' task IDs).
    if rec.get("project_id") and rec["project_id"] != project_id:
        raise HTTPException(404, f"task {task_id!r} not found in this project")
    return rec


@router.get("/projects/{project_id}/ingest/tasks")
async def ingest_tasks(project_id: str):
    """Return all tracked ingest tasks for a project (most recent first)."""
    items = list_tasks(project_id=project_id)
    items.sort(key=lambda t: t.get("started_at") or 0, reverse=True)
    return {"tasks": items}


@router.post("/queue/pause")
async def queue_pause():
    """Pause the ingestion queue. Running tasks finish; pending tasks wait."""
    from ...queue.service import get_default_queue_service
    svc = get_default_queue_service()
    svc.pause()
    status = svc.get_status()
    return {"status": "paused", "pending": status["pending_count"], "running": status["running_count"]}


@router.post("/queue/resume")
async def queue_resume():
    """Resume the ingestion queue. Pending tasks start processing."""
    from ...queue.service import get_default_queue_service
    svc = get_default_queue_service()
    svc.resume()
    # Fill worker slots
    for _ in range(5):
        if not svc.advance():
            break
    status = svc.get_status()
    return {"status": "resumed", "pending": status["pending_count"], "running": status["running_count"]}


@router.get("/queue/status")
async def queue_status():
    """Return current queue statistics."""
    from ...queue.service import get_default_queue_service
    return get_default_queue_service().get_status()
