# src/project/identity.py
"""Project identity — UUID v4 generation + project.json I/O."""
import json
import logging
import uuid
from dataclasses import asdict, dataclass
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
        llm_provider: configured LLM provider name (None = use global default)
        llm_model: configured LLM model name (None = use provider default)
    """
    id: str
    name: str
    created_at: int
    schema_version: str = "v2.0"
    llm_provider: str | None = None
    llm_model: str | None = None
    template_id: str | None = None
    template_version: str | None = None
    template_hash: str | None = None
    contract_hash: str | None = None

    PROJECT_JSON_PATH = ".llm-wiki/project.json"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Strip None-valued optional fields so old project.json files
        # don't grow noise.
        for key in (
            "llm_provider", "llm_model", "template_id", "template_version",
            "template_hash", "contract_hash",
        ):
            if d.get(key) is None:
                del d[key]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectIdentity":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            schema_version=data.get("schema_version", "v2.0"),
            llm_provider=data.get("llm_provider"),
            llm_model=data.get("llm_model"),
            template_id=data.get("template_id"),
            template_version=data.get("template_version"),
            template_hash=data.get("template_hash"),
            contract_hash=data.get("contract_hash"),
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


def resolve_project_template(project_root: Path):
    """Compile and persist the project's binding, preserving legacy projects."""
    from ..templates.compiler import compile_project_template
    from ..templates.contract import persist_template_snapshot
    from ..lib.write_hooks import safe_write

    project_root = Path(project_root)
    project_json = project_root / ProjectIdentity.PROJECT_JSON_PATH
    project_id = ensure_project_id(project_root)
    data = json.loads(project_json.read_text(encoding="utf-8"))
    identity = ProjectIdentity.from_dict(data)
    template_id = identity.template_id or "general@compat"
    template_version = identity.template_version or "compat"
    snapshot, contract = compile_project_template(
        project_root, template_id=template_id, template_version=template_version,
        expected_hash=identity.template_hash,
    )
    snapshot = persist_template_snapshot(project_root, contract)
    if (
        identity.template_id != snapshot.template_id
        or identity.template_version != snapshot.template_version
        or identity.template_hash != snapshot.template_hash
        or identity.contract_hash != snapshot.contract_hash
    ):
        data.update({
            "template_id": snapshot.template_id,
            "template_version": snapshot.template_version,
            "template_hash": snapshot.template_hash,
            "contract_hash": snapshot.contract_hash,
        })
        safe_write(project_json, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return snapshot, contract
