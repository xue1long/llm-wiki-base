"""Project registry queries — list + get.

Extracted from src/server/routes/projects.py. Routes now call these
and map ProjectNotFound to HTTPException(404).
"""
from __future__ import annotations

from pathlib import Path
import json
import os

from ..project.context import ProjectContext
from ..project.identity import ProjectIdentity
from ..utils.path import safe_resolve
from ..project.registry import GlobalRegistryStore


class ProjectNotFound(Exception):
    """No project matched the given id or name."""


def _rel_path(abs_path: str, base: str | None = None) -> str:
    """Return abs_path relative to base (default: CWD)."""
    try:
        base_val = safe_resolve(base) if base else safe_resolve(Path.cwd())
        return str(safe_resolve(abs_path).relative_to(base_val))
    except ValueError:
        return abs_path


def list_projects(base: str | None = None) -> dict:
    """Return {projects: [{id, name, path, last_opened, schema_version}, ...]}.

    Entries whose project directory no longer exists on disk are silently
    dropped (auto-cleaned from the registry) so stale test artifacts and
    deleted projects don't clutter the UI.
    """
    reg = GlobalRegistryStore.load()
    stale_ids: list[str] = []
    seen_names: set[str] = set()
    valid: list[dict] = []

    for e in sorted(reg.projects.values(), key=lambda e: e.last_opened or 0, reverse=True):
        if not Path(e.path).exists():
            stale_ids.append(e.id)
            continue
        # Skip duplicate names — entries are sorted by last_opened desc,
        # so the first (most recently used) wins.
        if e.name in seen_names:
            continue
        seen_names.add(e.name)
        valid.append({
            "id": e.id,
            "name": e.name,
            "path": _rel_path(e.path, base),
            "last_opened": e.last_opened,
            "schema_version": e.schema_version,
        })

    # Auto-heal: remove stale entries from registry so they don't accumulate
    if stale_ids:
        for pid in stale_ids:
            GlobalRegistryStore.remove(pid)

    # The server accepts an explicit project root and can still serve it when
    # the user config directory is read-only (common in sandboxes/containers).
    # Keep this discovery read-only; normal registry entries remain preferred.
    explicit_root = os.environ.get("RUFLO_PROJECT_ROOT")
    if explicit_root:
        root = Path(explicit_root).expanduser()
        project_json = root / ProjectIdentity.PROJECT_JSON_PATH
        try:
            identity = ProjectIdentity.from_dict(
                json.loads(project_json.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            identity = None
        if identity and root.is_dir() and not any(p["id"] == identity.id for p in valid):
            valid.insert(0, {
                "id": identity.id,
                "name": identity.name or root.name,
                "path": _rel_path(str(root), base),
                "last_opened": 0,
                "schema_version": identity.schema_version,
            })

    return {"projects": valid}


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
        explicit_root = os.environ.get("RUFLO_PROJECT_ROOT")
        if explicit_root:
            root = Path(explicit_root).expanduser()
            project_json = root / ProjectIdentity.PROJECT_JSON_PATH
            try:
                identity = ProjectIdentity.from_dict(
                    json.loads(project_json.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                identity = None
            if identity and project_id in {identity.id, identity.name}:
                return {
                    "id": identity.id,
                    "name": identity.name or root.name,
                    "path": str(root),
                    "last_opened": 0,
                    "schema_version": identity.schema_version,
                }
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
    knowledge_base = safe_resolve(Path.cwd() / "knowledge")
    project_root = safe_resolve(knowledge_base / name)
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


def delete_project(project_id: str) -> None:
    """Remove a project entry from the global registry.

    This does NOT delete project files on disk — it only removes the
    registry record so the project no longer appears in the UI.

    Raises:
        ProjectNotFound: if project_id doesn't exist.
    """
    entry = GlobalRegistryStore.by_id(project_id)
    if not entry:
        raise ProjectNotFound(f"Project not found: {project_id}")
    GlobalRegistryStore.remove(project_id)
