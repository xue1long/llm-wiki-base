# src/project/context.py
"""ProjectContext — resolved, ready-to-use project handle.

Created via:
- ProjectContext.from_path(path) — for explicit init / discovery
- ProjectContext.resolve(project_arg) — for CLI entry points
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils.path import safe_resolve
from ..lib.time import now_ms

from .identity import ProjectIdentity, ensure_project_id
from .paths import config_dir as _config_dir
from .paths import last_project_path as _last_project_path
from .registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
    registry_path as _registry_path,
)


class ProjectNotFoundError(Exception):
    """Raised when resolve() can't find a project from any source.

    Includes a hint message guiding user to fix.
    """
    def __init__(self, message: str):
        super().__init__(message)


@dataclass
class ProjectContext:
    """Resolved project handle passed to every spec function."""
    identity: ProjectIdentity
    path: Path
    name: str
    schema_version: str = "v2.0"

    @property
    def id(self) -> str:
        return self.identity.id

    @classmethod
    def from_path(cls, project_path: Path, name: str | None = None) -> "ProjectContext":
        """Initialize or read project at given path.

        1. ensure_project_id → generates or reads UUID
        2. Register in GlobalRegistryStore (idempotent)
        3. Return ProjectContext

        Args:
            project_path: KB root directory
            name: override name (defaults to project_path.name)
        """
        project_path = safe_resolve(project_path)
        uuid = ensure_project_id(project_path)

        # Read back identity to get full data
        project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH
        import json
        identity = ProjectIdentity.from_dict(json.loads(project_json.read_text(encoding="utf-8")))

        # Register / update in global registry.
        # Priority: explicit name arg > project.json's name field > directory name.
        resolved_name = name or identity.name or project_path.name
        entry = ProjectRegistryEntry(
            id=uuid,
            path=str(project_path),
            name=resolved_name,
            last_opened=now_ms(),
            schema_version=identity.schema_version,
        )
        GlobalRegistryStore.upsert(entry)

        return cls(
            identity=identity,
            path=project_path,
            name=resolved_name,
            schema_version=identity.schema_version,
        )

    @classmethod
    def resolve(
        cls,
        project_arg: str | None,
        by_id_only: bool = False,
    ) -> "ProjectContext":
        """4-step resolution chain:

        1. project_arg given → lookup in registry by id or name
        2. CWD upward search for `.llm-wiki/project.json`
        3. last_project.json pointer
        4. ProjectNotFoundError with hint

        Args:
            project_arg: explicit UUID or name from --project arg (None = auto-resolve)
            by_id_only: if True, skip steps 2-3 (used by HTTP API for safety)

        Returns:
            ProjectContext for the resolved project
        """
        # Step 1: explicit --project arg
        if project_arg:
            entry = GlobalRegistryStore.by_id(project_arg)
            if entry:
                return cls._from_registry_entry(entry)
            entry = GlobalRegistryStore.by_name(project_arg)
            if entry:
                return cls._from_registry_entry(entry)
            raise ProjectNotFoundError(
                f"No project with id/name '{project_arg}'. "
                f"Run `python -m src.cli project list` to see known projects."
            )

        if by_id_only:
            # HTTP API: don't fall back to CWD or last_project
            raise ProjectNotFoundError(
                "project_id required for HTTP API calls. "
                "Pass ?project_id=<uuid> or X-Project-Id header."
            )

        # Step 2: CWD upward search
        cwd = Path.cwd().resolve()
        for ancestor in [cwd, *cwd.parents]:
            project_json = ancestor / ProjectIdentity.PROJECT_JSON_PATH
            if project_json.exists():
                try:
                    return cls.from_path(ancestor)
                except Exception:
                    continue

        # Step 3: last_project.json
        last = GlobalRegistryStore.load_last_project()
        if last:
            entry = GlobalRegistryStore.by_id(last.id)
            if entry:
                return cls._from_registry_entry(entry)

        # Step 4: error
        raise ProjectNotFoundError(
            "No project resolved. Choose one of:\n"
            "  1. Run `python -m src.cli project init <path>` to create\n"
            "  2. Run `python -m src.cli project list` to see known projects\n"
            "  3. `cd` into a project directory (has `.llm-wiki/project.json`)\n"
            "  4. Pass `--project <id|name>` flag"
        )

    @classmethod
    def _from_registry_entry(cls, entry: ProjectRegistryEntry) -> "ProjectContext":
        """Build ProjectContext from registry entry (read project.json for identity)."""
        project_path = Path(entry.path)
        if not project_path.exists():
            raise ProjectNotFoundError(
                f"Project '{entry.name}' registered but path no longer exists: {project_path}. "
                f"Run `python -m src.cli project forget {entry.id}` to clean up."
            )
        # Load identity from project.json (don't regenerate)
        import json
        project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH
        identity = ProjectIdentity.from_dict(
            json.loads(project_json.read_text(encoding="utf-8"))
        )
        # Update last_opened
        entry.last_opened = now_ms()
        GlobalRegistryStore.upsert(entry)
        return cls(
            identity=identity,
            path=safe_resolve(project_path),
            name=entry.name,
            schema_version=identity.schema_version,
        )
