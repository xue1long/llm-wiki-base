# src/server/routes/projects.py
from fastapi import APIRouter, HTTPException
from ...services import projects as projects_service

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
async def list_projects():
    """List all projects in the global registry."""
    return projects_service.list_projects()


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get one project by id or name."""
    try:
        return projects_service.get_project(project_id)
    except projects_service.ProjectNotFound as e:
        raise HTTPException(404, str(e))
