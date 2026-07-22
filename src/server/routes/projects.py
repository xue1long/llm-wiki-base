# src/server/routes/projects.py
from fastapi import APIRouter, HTTPException
from ...project.context import ProjectContext, ProjectNotFoundError
from ...project.registry import GlobalRegistryStore

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects")
async def list_projects():
    reg = GlobalRegistryStore.load()
    return {
        "projects": [
            {"id": e.id, "name": e.name, "path": e.path, "schema_version": e.schema_version}
            for e in reg.projects.values()
        ]
    }


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    entry = GlobalRegistryStore.by_id(project_id) or GlobalRegistryStore.by_name(project_id)
    if not entry:
        raise HTTPException(404, f"Project not found: {project_id}")
    return entry.to_dict()
