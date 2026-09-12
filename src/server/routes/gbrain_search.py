"""HTTP lifecycle controls for optional project-level GBrain search."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Literal

from ...integrations.gbrain import service as gbrain_service
from ...project.context import ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["gbrain-search"])


class ConfirmRequest(BaseModel):
    confirm: bool = False


class SearchConfigRequest(BaseModel):
    gbrain_mode: Literal["conservative", "balanced", "tokenmax"]
    result_limit: int
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


@router.get("/projects/{project_id}/gbrain-search/config")
async def search_config(project_id: str):
    return _call(gbrain_service.get_search_config, project_id)


@router.put("/projects/{project_id}/gbrain-search/config")
async def update_search_config(project_id: str, body: SearchConfigRequest):
    return _call(
        gbrain_service.update_search_config,
        project_id,
        gbrain_mode=body.gbrain_mode,
        result_limit=body.result_limit,
        confirm=body.confirm,
    )


@router.get("/projects/{project_id}/gbrain")
async def runtime_status(project_id: str):
    return _call(gbrain_service.get_runtime_status, project_id)


@router.post("/projects/{project_id}/gbrain/setup", status_code=202)
async def setup(
    project_id: str,
    body: ConfirmRequest,
    background_tasks: BackgroundTasks = None,
):
    result = _call(gbrain_service.setup_runtime_job, project_id, confirm=body.confirm)
    if background_tasks is not None and result.get("status") == "queued":
        from ...integrations.gbrain.worker import run_runtime_setup_job_for_project
        background_tasks.add_task(run_runtime_setup_job_for_project, project_id, result["jobId"])
    return result


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


@router.get("/projects/{project_id}/gbrain/jobs/{job_id}")
@router.get("/projects/{project_id}/gbrain-search/jobs/{job_id}")
async def job(project_id: str, job_id: str):
    return _call(gbrain_service.get_search_job, project_id, job_id)
