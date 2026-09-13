"""Small JSON-backed persistence for the Skill Manager control plane."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from ..project.paths import config_dir
from .types import Artifact, Deployment, FileEntry, SourceSpec


INFLIGHT_OPERATION_STATUSES = frozenset(
    {"queued", "downloading", "validating", "installing"}
)
_PROCESS_LOCK = threading.RLock()
_LOCK_DEPTH = threading.local()


class StorageError(ValueError):
    """Stable fail-closed error for Skill Manager state."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@contextmanager
def manager_lock(root: Path) -> Iterator[None]:
    """Serialize manager writes in-process and across processes."""

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    key = str(root.resolve())
    depths = getattr(_LOCK_DEPTH, "values", {})
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    lock_path = root / "manager.lock"
    with _PROCESS_LOCK:
        depths[key] = 1
        _LOCK_DEPTH.values = depths
        with lock_path.open("a+b") as stream:
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                depths.pop(key, None)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageError("STATE_CORRUPT", f"invalid manager state: {path.name}") from exc
    if not isinstance(payload, dict):
        raise StorageError("STATE_CORRUPT", f"manager state must be an object: {path.name}")
    return payload


def _artifact_to_dict(artifact: Artifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "content_hash": artifact.content_hash,
        "files": [asdict(entry) for entry in artifact.files],
        "total_bytes": artifact.total_bytes,
        "source": {"path": str(artifact.source.path), "kind": artifact.source.kind},
    }


def _artifact_from_dict(payload: dict[str, Any]) -> Artifact:
    try:
        source = payload["source"]
        files = tuple(FileEntry(**entry) for entry in payload["files"])
        return Artifact(
            artifact_id=str(payload["artifact_id"]),
            name=str(payload["name"]),
            content_hash=str(payload["content_hash"]),
            files=files,
            total_bytes=int(payload["total_bytes"]),
            source=SourceSpec(path=source["path"], kind=str(source["kind"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError("STATE_CORRUPT", "invalid Artifact state") from exc


def _deployment_to_dict(deployment: Deployment) -> dict[str, str]:
    return asdict(deployment)


def _deployment_from_dict(payload: dict[str, Any]) -> Deployment:
    try:
        return Deployment(
            deployment_id=str(payload["deployment_id"]),
            artifact_id=str(payload["artifact_id"]),
            target_id=str(payload["target_id"]),
            target_path=str(payload["target_path"]),
            content_hash=str(payload["content_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError("STATE_CORRUPT", "invalid Deployment state") from exc


class SkillManagerStorage:
    """Persist manager metadata without introducing a database."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else config_dir() / "skill-manager"

    def save_artifact(self, artifact: Artifact) -> None:
        with manager_lock(self.root):
            _atomic_write_json(
                self.root / "artifacts" / artifact.artifact_id / "artifact.json",
                _artifact_to_dict(artifact),
            )

    def load_artifact(self, artifact_id: str) -> Artifact:
        path = self.root / "artifacts" / artifact_id / "artifact.json"
        if not path.is_file():
            raise StorageError("NOT_FOUND", "Artifact was not found")
        return _artifact_from_dict(_read_json(path))

    def save_deployment(self, deployment: Deployment) -> None:
        with manager_lock(self.root):
            _atomic_write_json(
                self.root / "deployments" / f"{deployment.deployment_id}.json",
                _deployment_to_dict(deployment),
            )

    def load_deployment(self, deployment_id: str) -> Deployment:
        path = self.root / "deployments" / f"{deployment_id}.json"
        if not path.is_file():
            raise StorageError("NOT_FOUND", "Deployment was not found")
        return _deployment_from_dict(_read_json(path))

    def delete_deployment(self, deployment_id: str) -> None:
        with manager_lock(self.root):
            (self.root / "deployments" / f"{deployment_id}.json").unlink(missing_ok=True)

    def write_manifest(self, payload: dict[str, Any]) -> None:
        with manager_lock(self.root):
            _atomic_write_json(self.root / "manifest.json", payload)

    def read_manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        if not path.is_file():
            raise StorageError("NOT_FOUND", "manager manifest was not found")
        return _read_json(path)

    def save_operation(self, payload: dict[str, Any]) -> None:
        operation_id = payload.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            raise StorageError("INVALID_OPERATION", "operation id is required")
        with manager_lock(self.root):
            _atomic_write_json(self.root / "operations" / f"{operation_id}.json", payload)

    def load_operation(self, operation_id: str) -> dict[str, Any]:
        path = self.root / "operations" / f"{operation_id}.json"
        if not path.is_file():
            raise StorageError("NOT_FOUND", "operation was not found")
        return _read_json(path)

    def recover_inflight_operations(self) -> list[str]:
        operations = self.root / "operations"
        if not operations.is_dir():
            return []
        recovered: list[str] = []
        with manager_lock(self.root):
            for path in sorted(operations.glob("*.json")):
                payload = _read_json(path)
                if payload.get("status") not in INFLIGHT_OPERATION_STATUSES:
                    continue
                payload["status"] = "failed"
                payload["error_code"] = "server_restarted"
                _atomic_write_json(path, payload)
                recovered.append(str(payload.get("id") or path.stem))
        return recovered
