# src/server/routes/search.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ...project.context import ProjectNotFoundError
from ...services import search as search_service

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    topK: int = 10
    includeContent: bool = False
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"


@router.post("/projects/{project_id}/search")
async def search(project_id: str, body: SearchRequest):
    """Hybrid (semantic + keyword) search over the project's wiki tree."""
    try:
        return await search_service.search(project_id, body.query, body.topK, body.mode)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
