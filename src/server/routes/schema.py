# src/server/routes/schema.py
from fastapi import APIRouter
from ...schemas.registry import MigrationRegistry

router = APIRouter(prefix="/api/v1", tags=["schema"])


@router.get("/projects/{project_id}/schema")
async def get_schema(project_id: str):
    """List registered schemas + current versions (read-only)."""
    return {
        "schemas": list({(s, f.value) for s, f, _ in MigrationRegistry._migrations.keys()}),
    }
