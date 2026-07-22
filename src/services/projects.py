"""Project registry queries — list + get.

Extracted from src/server/routes/projects.py. Routes now call these
and map ProjectNotFound to HTTPException(404).
"""
from __future__ import annotations

from ..project.registry import GlobalRegistryStore


class ProjectNotFound(Exception):
    """No project matched the given id or name."""


def list_projects() -> dict:
    """Return {projects: [{id, name, path, schema_version}, ...]}."""
    reg = GlobalRegistryStore.load()
    return {
        "projects": [
            {
                "id": e.id,
                "name": e.name,
                "path": e.path,
                "schema_version": e.schema_version,
            }
            for e in reg.projects.values()
        ]
    }


def get_project(project_id: str) -> dict:
    """Return the entry's dict for the given id or name.

    Raises:
        ProjectNotFound: if neither id nor name matches any entry.
    """
    entry = (
        GlobalRegistryStore.by_id(project_id)
        or GlobalRegistryStore.by_name(project_id)
    )
    if not entry:
        raise ProjectNotFound(f"Project not found: {project_id}")
    return entry.to_dict()
