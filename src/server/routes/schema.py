# src/server/routes/schema.py
from fastapi import APIRouter, HTTPException

from ...project.context import ProjectNotFoundError
from ...services import schema as schema_service

router = APIRouter(prefix="/api/v1", tags=["schema"])


@router.get("/projects/{project_id}/schema")
async def get_schema(project_id: str):
    """List migrations reachable up to the project's current schema_version.

    Returns 404 when the project id is not registered (audit I7). The
    previous behaviour returned 200 with an empty schemas list, which
    made unknown-project lookups indistinguishable from a known project
    that has no pending migrations.
    """
    try:
        return schema_service.get_schema(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc