# src/server/routes/schema.py
from fastapi import APIRouter

from ...services import schema as schema_service

router = APIRouter(prefix="/api/v1", tags=["schema"])


@router.get("/projects/{project_id}/schema")
async def get_schema(project_id: str):
    """List migrations reachable up to the project's current schema_version."""
    return schema_service.get_schema(project_id)
