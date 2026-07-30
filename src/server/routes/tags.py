# src/server/routes/tags.py
from fastapi import APIRouter, HTTPException
from ...project.context import ProjectNotFoundError
from ...services import tags as tags_service

router = APIRouter(prefix="/api/v1", tags=["tags"])


@router.get("/projects/{project_id}/tag-index")
async def tag_index(project_id: str):
    """Return namespace-aggregated tag counts across all wiki pages."""
    try:
        return tags_service.build_tag_index(project_id)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
