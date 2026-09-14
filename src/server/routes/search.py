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
    # V7.1.1 (RFC v6): added "tool" for reference-table pages (e.g. 百家姓).
    # Stage / multi-stage routing is left for the V7.2 retrieval-API RFC.
    type: Literal["concept", "entity", "source", "synthesis", "tool"] | None = None


@router.post("/projects/{project_id}/search")
async def search(project_id: str, body: SearchRequest):
    """Search the project's wiki tree with an explicit mode."""
    try:
        return await search_service.search(project_id, body.query, body.topK, body.mode, body.type)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
