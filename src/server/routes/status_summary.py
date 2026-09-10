"""Read-only project lifecycle status API."""
from fastapi import APIRouter, HTTPException

from ...project.context import ProjectNotFoundError
from ...services import status_summary as status_summary_service

router = APIRouter(prefix="/api/v1", tags=["status"])


@router.get("/projects/{project_id}/status-summary")
async def status_summary(project_id: str):
    """Return the RAW → KC → Wiki → Book lifecycle summary."""
    try:
        return status_summary_service.get_status_summary(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

