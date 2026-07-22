# src/server/routes/reviews.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
from ...project.context import ProjectContext, ProjectNotFoundError
from ...wiki.review import load_reviews, add_review, resolve_review, ReviewItem

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.get("/projects/{project_id}/reviews")
async def list_reviews(project_id: str, status: str = "open", type: Optional[str] = None, limit: int = 200):
    ctx = _resolve_ctx(project_id)
    items = load_reviews(ctx.paths)
    if status != "all":
        items = [i for i in items if i.status == status]
    if type:
        items = [i for i in items if i.type == type]
    items = items[:limit]
    return {
        "status": status,
        "count": len(items),
        "reviews": [
            {
                "id": i.id, "type": i.type, "title": i.title, "normalizedTitle": i.normalized_title,
                "detail": i.detail, "confidence": i.confidence, "searchQueries": i.search_queries,
                "pagePath": i.page_path, "createdAt": i.created_at, "sourceTaskId": i.source_task_id,
                "status": i.status,
            } for i in items
        ],
    }


class PatchReviewBody(BaseModel):
    resolved: bool
    action: str = "skip"


@router.patch("/projects/{project_id}/reviews/{review_id}")
async def patch_review(project_id: str, review_id: str, body: PatchReviewBody):
    ctx = _resolve_ctx(project_id)
    if body.resolved:
        resolve_review(ctx.paths, review_id, body.action)
    return {"ok": True}


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
