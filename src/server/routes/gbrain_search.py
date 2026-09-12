"""HTTP lifecycle controls for optional project-level GBrain search."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ...integrations.gbrain import service as gbrain_service
from ...project.context import ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["gbrain-search"])


class ConfirmRequest(BaseModel):
    confirm: bool = False


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ProjectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/gbrain-search")
async def status(project_id: str):
    return _call(gbrain_service.get_search_status, project_id)


@router.post("/projects/{project_id}/gbrain-search/enable", status_code=202)
async def enable(
    project_id: str,
    body: ConfirmRequest,
    background_tasks: BackgroundTasks = None,
):
    result = _call(gbrain_service.enable_search, project_id, confirm=body.confirm)
    if background_tasks is not None and result.get("status") == "queued":
        from ...integrations.gbrain.worker import run_search_job_for_project
        background_tasks.add_task(run_search_job_for_project, project_id, result["jobId"])
    return result


@router.post("/projects/{project_id}/gbrain-search/disable")
async def disable(project_id: str):
    return _call(gbrain_service.disable_search, project_id)


@router.post("/projects/{project_id}/gbrain-search/rebuild", status_code=202)
async def rebuild(
    project_id: str,
    body: ConfirmRequest,
    background_tasks: BackgroundTasks = None,
):
    result = _call(gbrain_service.rebuild_search, project_id, confirm=body.confirm)
    if background_tasks is not None and result.get("status") == "queued":
        from ...integrations.gbrain.worker import run_search_job_for_project
        background_tasks.add_task(run_search_job_for_project, project_id, result["jobId"])
    return result


@router.get("/projects/{project_id}/gbrain-search/jobs/{job_id}")
async def job(project_id: str, job_id: str):
    return _call(gbrain_service.get_search_job, project_id, job_id)
