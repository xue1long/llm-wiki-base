# src/project/identity.py
"""Project identity — UUID v4 generation + project.json I/O."""
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_logger = logging.getLogger(__name__)


@dataclass
class ProjectIdentity:
    """Per-project identity stored in `.llm-wiki/project.json`.

    Fields:
        id: UUID v4 (stable across filesystem moves/renames)
        name: human-readable project name (unique within registry)
        created_at: unix ms timestamp
        schema_version: current schema version (e.g., "v2.0")
    """
    id: str
    name: str
    created_at: int
    schema_version: str = "v2.0"

    PROJECT_JSON_PATH = ".llm-wiki/project.json"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectIdentity":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            schema_version=data.get("schema_version", "v2.0"),
        )


def ensure_project_id(project_path: Path) -> str:
    """Ensure `.llm-wiki/project.json` exists; return its UUID.

    - If file missing or corrupt → generate new UUID + write
    - If file valid → return existing UUID

    Args:
        project_path: KB root directory (e.g., `/home/user/research`)

    Returns:
        UUID v4 string (e.g., `550e8400-e29b-41d4-a716-446655440000`)
    """
    project_path = Path(project_path)
    project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH

    # Try to load existing
    if project_json.exists():
        try:
            data = json.loads(project_json.read_text(encoding="utf-8"))
            ident = ProjectIdentity.from_dict(data)
            if ident.id:
                return ident.id
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _logger.warning(f"[project-identity] corrupt project.json: {e}; regenerating")

    # Generate new
    ident = ProjectIdentity(
        id=str(uuid.uuid4()),
        name=project_path.name,
        created_at=_now_ms(),
    )
    project_json.parent.mkdir(parents=True, exist_ok=True)
    project_json.write_text(
        json.dumps(ident.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return ident.id


def _now_ms() -> int:
    """Unix epoch in milliseconds."""
    import time
    return int(time.time() * 1000)