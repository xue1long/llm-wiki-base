# src/server/routes/search.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
from ...project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    topK: int = 10
    includeContent: bool = False
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"


@router.post("/projects/{project_id}/search")
async def search(project_id: str, body: SearchRequest):
    ctx = _resolve_ctx(project_id)
    # Use existing searcher (assume wired later)
    from ...searcher.hybrid_search import hybrid_search
    results = await hybrid_search(ctx, body.query, top_k=body.topK, mode=body.mode)
    return {
        "mode": body.mode,
        "tokenHits": 0,         # Filled by hybrid_search
        "vectorHits": 0,
        "results": results,
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
