"""Application adapter for the independent Skill Manager core."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from ..skill_manager import api
from ..skill_manager.agents import discover_targets
from ..skill_manager.storage import SkillManagerStorage
from ..skill_manager.types import SourceSpec


def _storage() -> SkillManagerStorage:
    return SkillManagerStorage()


def list_agents() -> dict[str, Any]:
    return {"agents": [{"id": t.id, "scope": t.scope, "exists": t.exists} for t in discover_targets()]}


def inspect_artifact(source: str) -> dict[str, Any]:
    item = api.inspect_source(SourceSpec(Path(source)))
    return {"package_type": item.package_type, "name": item.name, "artifact_id": item.artifact_id,
            "content_hash": item.content_hash, "file_count": len(item.files), "total_bytes": item.total_bytes}


def import_artifact(source: str, plan_hash: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("CONFIRMATION_REQUIRED")
    item = api.import_artifact(SourceSpec(Path(source)), plan_hash=plan_hash,
                               confirmation="confirm", storage=_storage())
    return {"artifact_id": item.artifact_id, "content_hash": item.content_hash, "name": item.name}


def list_library() -> dict[str, Any]:
    storage = _storage()
    root = storage.root / "artifacts"
    artifacts = []
    for metadata in sorted(root.glob("*/artifact.json")) if root.is_dir() else ():
        item = storage.load_artifact(metadata.parent.name)
        artifacts.append({"artifact_id": item.artifact_id, "name": item.name,
                          "content_hash": item.content_hash, "file_count": len(item.files),
                          "total_bytes": item.total_bytes})
    return {"artifacts": artifacts}


def plan_artifact(artifact_id: str, target_ids: Sequence[str]) -> dict[str, Any]:
    item = api.plan_deployment(artifact_id, target_ids, storage=_storage())
    return {"plan_hash": item.plan_hash, "artifact_id": item.artifact_id,
            "targets": [{"id": t.target_id, "status": t.status, "reason": t.reason} for t in item.targets]}


def apply_artifact(artifact_id: str, target_ids: Sequence[str], plan_hash: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("CONFIRMATION_REQUIRED")
    storage = _storage()
    item = api.plan_deployment(artifact_id, target_ids, storage=storage)
    result = api.apply_deployment(item, plan_hash=plan_hash, confirmation="confirm", storage=storage)
    return {"operation_id": result.operation_id, "status": result.status,
            "artifact_id": result.artifact_id, "results": list(result.results),
            **({"error_code": result.error_code} if result.error_code else {})}


def get_operation(operation_id: str) -> dict[str, Any]:
    payload = _storage().load_operation(operation_id)
    return {"operation_id": payload.get("id", operation_id), "status": payload.get("status", "failed"),
            "artifact_id": payload.get("artifact_id"), "results": payload.get("results", []),
            **({"error_code": payload["error_code"]} if payload.get("error_code") else {})}


def list_operations() -> dict[str, Any]:
    storage = _storage()
    root = storage.root / "operations"
    operations = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else ():
        payload = storage.load_operation(path.stem)
        operations.append({"operation_id": payload.get("id", path.stem), "status": payload.get("status", "failed"),
                           "artifact_id": payload.get("artifact_id"),
                           **({"error_code": payload["error_code"]} if payload.get("error_code") else {})})
    return {"operations": operations}
