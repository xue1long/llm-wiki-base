"""Wiki structure routes: graph + lint.

Spec: FRONTEND_DESIGN.md §14.4 and §14.5.
"""
from fastapi import APIRouter, HTTPException

from ...project.context import ProjectNotFoundError
from ...services import wiki_analysis as analysis_service

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.get("/projects/{project_id}/wiki/graph")
async def wiki_graph(project_id: str):
    """Return {nodes, edges, counts} derived from wiki frontmatter relations
    and markdown links."""
    try:
        return analysis_service.graph(project_id)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/lint")
async def lint(project_id: str):
    """Heuristic wiki health: orphans, dangling edges, missing-id counts."""
    try:
        return analysis_service.lint(project_id)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/content-health")
async def content_health(project_id: str):
    """Return a read-only aggregate of wiki content and triage state."""
    try:
        return analysis_service.content_health(project_id)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
