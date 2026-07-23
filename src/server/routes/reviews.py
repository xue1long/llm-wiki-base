# src/server/routes/reviews.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ...project.context import ProjectNotFoundError
from ...services import reviews as reviews_service

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.get("/projects/{project_id}/reviews")
async def list_reviews(project_id: str, status: str = "open", type: Optional[str] = None, limit: int = 200):
    """List review queue items for a project."""
    try:
        return reviews_service.list_reviews(project_id, status, type, limit)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))


class PatchReviewBody(BaseModel):
    resolved: bool
    action: str = "skip"


@router.patch("/projects/{project_id}/reviews/{review_id}")
async def patch_review(project_id: str, review_id: str, body: PatchReviewBody):
    """Mark a review as resolved (or unresolve)."""
    try:
        if body.resolved:
            reviews_service.resolve_review(project_id, review_id, body.action)
        return {"ok": True}
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
