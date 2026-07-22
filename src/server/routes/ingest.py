# src/server/routes/ingest.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Union
from pathlib import Path
from ...project.context import ProjectContext, ProjectNotFoundError
from ...queue.queue import enqueue_task, _default_state
from ...types import SourceType

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: Union[str, dict]   # URL or {"folder": path}
    folderContext: str | None = None


@router.post("/projects/{project_id}/ingest")
async def ingest(project_id: str, body: IngestRequest):
    ctx = _resolve_ctx(project_id)
    if isinstance(body.source, str):
        source = body.source
        stype = SourceType.URL if source.startswith("http") else SourceType.FILE
    else:
        source = body.source.get("folder", "")
        stype = SourceType.FILE
    from ...utils.idempotency import generate_task_hash
    task_hash = generate_task_hash(stype, source, body.folderContext or "")
    task_id = enqueue_task(source, stype, task_hash)
    if not task_id:
        return {"status": "ignored", "taskId": None, "reason": "Duplicate"}
    return {"status": "queued", "taskId": task_id, "reason": None}


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
