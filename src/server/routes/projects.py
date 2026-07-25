# src/server/routes/projects.py
from pathlib import Path
from fastapi import APIRouter, HTTPException
from ...services import projects as projects_service

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
async def list_projects():
    """List all projects in the global registry."""
    return projects_service.list_projects()


@router.get("/projects/current")
async def current_project():
    """Return the project whose `path` matches the server's CWD.

    Spec: ruflo-kb ships with many test fixtures in the global registry.
    The user expects the frontend to default to the project they actually
    launched the server from — not whatever happens to be first in the
    registry. We resolve the server's CWD and match it against project.path.
    Returns 404 if no match is found.
    """
    cwd = str(Path.cwd()).replace("\\", "/").rstrip("/")
    projects = projects_service.list_projects().get("projects", [])
    # Prefer exact path match; fall back to prefix-match on path's directory
    for p in projects:
        proj_path = (p.get("path") or "").replace("\\", "/").rstrip("/")
        if proj_path and proj_path.lower() == cwd.lower():
            return p
    # Fallback: match if CWD is under the project's path (e.g. cwd is a
    # sub-directory of the project)
    for p in projects:
        proj_path = (p.get("path") or "").replace("\\", "/").rstrip("/")
        if proj_path and cwd.lower().startswith(proj_path.lower() + "/"):
            return p
    raise HTTPException(404, f"no project registered for CWD={cwd!r}")


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get one project by id or name."""
    try:
        return projects_service.get_project(project_id)
    except projects_service.ProjectNotFound as e:
        raise HTTPException(404, str(e))
