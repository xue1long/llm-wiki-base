# src/server/routes/projects.py
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

from ...services import projects as projects_service

router = APIRouter(prefix="/api/v1", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    template: str | None = None

    @validator("name")
    def name_must_be_safe(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9_-]{1,64}$", v):
            raise ValueError("Name must be 1-64 chars, alphanumeric/dash/underscore only")
        return v


@router.get("/projects")
async def list_projects(base: str | None = None):
    """List all projects in the global registry.

    Query param base: if provided, path field is relative to this path.
    """
    return projects_service.list_projects(base=base)


@router.post("/projects")
async def create_project(body: CreateProjectRequest):
    """Create a new project under CWD /knowledge/<name>."""
    try:
        if body.template:
            from ...templates import load
            load(body.template)  # validate before registering a new project
        result = projects_service.create_project(body.name)
        if body.template:
            from ...templates import apply_template
            apply_template(body.template, result["path"], force=True)
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


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


@router.post("/projects/{project_id}/select")
async def select_project(project_id: str):
    """Set the active project (writes last_project.json)."""
    try:
        result = projects_service.select_project(project_id)
        return {"ok": True, "id": result["id"], "name": result["name"]}
    except projects_service.ProjectNotFound as e:
        raise HTTPException(404, str(e))


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get one project by id or name."""
    try:
        return projects_service.get_project(project_id)
    except projects_service.ProjectNotFound as e:
        raise HTTPException(404, str(e))


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """Remove a project from the global registry (does NOT delete files)."""
    try:
        projects_service.delete_project(project_id)
        return {"ok": True}
    except projects_service.ProjectNotFound as e:
        raise HTTPException(404, str(e))
