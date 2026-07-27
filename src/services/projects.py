"""Project registry queries — list + get.

Extracted from src/server/routes/projects.py. Routes now call these
and map ProjectNotFound to HTTPException(404).
"""
from __future__ import annotations

from pathlib import Path

from ..project.context import ProjectContext
from ..project.registry import GlobalRegistryStore


class ProjectNotFound(Exception):
    """No project matched the given id or name."""


def _rel_path(abs_path: str, base: str | None = None) -> str:
    """Return abs_path relative to base (default: CWD)."""
    try:
        base_val = Path(base) if base else Path.cwd()
        return str(Path(abs_path).resolve().relative_to(base_val.resolve()))
    except ValueError:
        return abs_path


def list_projects(base: str | None = None) -> dict:
    """Return {projects: [{id, name, path, last_opened, schema_version}, ...]}."""
    reg = GlobalRegistryStore.load()
    entries = sorted(reg.projects.values(), key=lambda e: e.last_opened or 0, reverse=True)
    return {
        "projects": [
            {
                "id": e.id,
                "name": e.name,
                "path": _rel_path(e.path, base),
                "last_opened": e.last_opened,
                "schema_version": e.schema_version,
            }
            for e in entries
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


def create_project(name: str) -> dict:
    """Create a new project under CWD /knowledge/<name>.

    Args:
        name: project name (directory will be <cwd>/knowledge/<name>)

    Returns:
        dict with id, name, path of the newly created project.

    Raises:
        ValueError: if name is empty, contains path separators, or escapes
            the knowledge directory after resolution.
    """
    if not name or name in (".", ".."):
        raise ValueError("Invalid project name")
    if any(c in name for c in "/\\"):
        raise ValueError("Project name must not contain path separators")
    knowledge_base = (Path.cwd() / "knowledge").resolve()
    project_root = (knowledge_base / name).resolve()
    if not str(project_root).startswith(str(knowledge_base) + str(knowledge_base._flavour.sep)):
        raise ValueError("Project path escapes knowledge directory")
    ctx = ProjectContext.from_path(project_root, name=name)
    entry = GlobalRegistryStore.by_id(ctx.id)
    return {
        "id": entry.id,
        "name": entry.name,
        "path": entry.path,
    }


def select_project(project_id: str) -> dict:
    """Set the active project via last_project.json pointer.

    Raises:
        ProjectNotFound: if project_id doesn't exist.
    """
    entry = GlobalRegistryStore.by_id(project_id)
    if not entry:
        raise ProjectNotFound(f"Project not found: {project_id}")
    # Update last_opened timestamp
    import time
    entry.last_opened = int(time.time() * 1000)
    GlobalRegistryStore.upsert(entry)
    GlobalRegistryStore.save_last_project(entry.id, entry.path)
    return entry.to_dict()
