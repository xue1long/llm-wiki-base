"""HTTP adapter for Skill Manager operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services import skill_manager as service
from ...skill_manager.storage import StorageError

router = APIRouter(prefix="/api/v1/skill-manager", tags=["skill-manager"])


class SourceRequest(BaseModel):
    source: str


class ImportRequest(SourceRequest):
    plan_hash: str
    confirm: bool = False


class PlanRequest(BaseModel):
    artifact_id: str
    target_ids: list[str] = Field(min_length=1)


class ApplyRequest(PlanRequest):
    plan_hash: str
    confirm: bool = False


def _call(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except StorageError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 400
        raise HTTPException(status, {"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        code = getattr(exc, "code", None) or ("CONFIRMATION_REQUIRED" if str(exc) == "CONFIRMATION_REQUIRED" else "INVALID_ARGUMENT")
        raise HTTPException(400, {"code": code, "message": str(exc)}) from exc


@router.get("/agents")
def get_agents() -> dict[str, Any]:
    return _call(service.list_agents)


@router.get("/library")
def get_library() -> dict[str, Any]:
    return _call(service.list_library)


@router.post("/artifacts/inspect")
def inspect(body: SourceRequest) -> dict[str, Any]:
    return _call(service.inspect_artifact, body.source)


@router.post("/artifacts/import")
def import_artifact(body: ImportRequest) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(400, {"code": "CONFIRMATION_REQUIRED", "message": "explicit confirmation is required"})
    return _call(service.import_artifact, body.source, body.plan_hash, body.confirm)


@router.post("/deployments/plan")
def plan(body: PlanRequest) -> dict[str, Any]:
    return _call(service.plan_artifact, body.artifact_id, body.target_ids)


@router.post("/deployments/apply", status_code=202)
def apply(body: ApplyRequest) -> dict[str, Any]:
    if not body.confirm:
        raise HTTPException(400, {"code": "CONFIRMATION_REQUIRED", "message": "explicit confirmation is required"})
    return _call(service.apply_artifact, body.artifact_id, body.target_ids, body.plan_hash, body.confirm)


@router.get("/operations/{operation_id}")
def operation(operation_id: str) -> dict[str, Any]:
    return _call(service.get_operation, operation_id)
