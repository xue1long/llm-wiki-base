# src/project/context.py
"""ProjectContext — resolved, ready-to-use project handle.

Created via:
- ProjectContext.from_path(path) — for explicit init / discovery
- ProjectContext.resolve(project_arg) — for CLI entry points
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .identity import ProjectIdentity, ensure_project_id
from .paths import config_dir as _config_dir
from .paths import last_project_path as _last_project_path
from .registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
    registry_path as _registry_path,
)


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
        project_path = Path(project_path).resolve()
        uuid = ensure_project_id(project_path)

        # Read back identity to get full data
        project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH
        import json
        identity = ProjectIdentity.from_dict(json.loads(project_json.read_text(encoding="utf-8")))

        # Register / update in global registry
        resolved_name = name or project_path.name
        entry = ProjectRegistryEntry(
            id=uuid,
            path=str(project_path),
            name=resolved_name,
            last_opened=_now_ms(),
            schema_version=identity.schema_version,
        )
        GlobalRegistryStore.upsert(entry)

        return cls(
            identity=identity,
            path=project_path,
            name=resolved_name,
            schema_version=identity.schema_version,
        )


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)
