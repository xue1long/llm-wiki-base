"""Small, filesystem-backed contract for task identity and recovery."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def _root(root: Path | str | None = None) -> Path:
    return Path(root or os.environ.get("RUFLO_TASK_STATE_DIR") or Path.cwd() / ".index")


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    source_path: Path
    source_hash: str
    template_version: str
    contract_version: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls, task_id: str, source_path: Path | str, source_text: str, *,
        template_version: str, contract_version: str,
    ) -> "TaskContext":
        return cls(
            task_id=str(task_id),
            source_path=Path(source_path),
            source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            template_version=str(template_version),
            contract_version=str(contract_version),
        )

    @property
    def idempotency_key(self) -> str:
        return f"{self.contract_version}:{self.template_version}:{self.source_hash}"


class TaskState(str, Enum):
    CREATED = "created"
    SCREENED = "screened"
    ANALYZED = "analyzed"
    REVIEWED = "reviewed"
    GENERATED = "generated"
    VALIDATED = "validated"
    COMMITTED = "committed"
    REVIEW_REQUIRED = "review_required"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class InvalidTaskTransition(ValueError):
    pass


_LEGAL_TRANSITIONS = {
    (TaskState.CREATED, target) for target in (TaskState.SCREENED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.SCREENED, target) for target in (TaskState.ANALYZED, TaskState.REVIEW_REQUIRED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.ANALYZED, target) for target in (TaskState.REVIEWED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.REVIEWED, target) for target in (TaskState.GENERATED, TaskState.REVIEW_REQUIRED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.GENERATED, target) for target in (TaskState.VALIDATED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.VALIDATED, target) for target in (TaskState.COMMITTED, TaskState.FAILED, TaskState.QUARANTINED)
} | {
    (TaskState.REVIEW_REQUIRED, target) for target in (TaskState.REVIEWED, TaskState.FAILED, TaskState.QUARANTINED)
}


def transition(current: TaskState, target: TaskState) -> None:
    if (current, target) not in _LEGAL_TRANSITIONS:
        raise InvalidTaskTransition(f"invalid task transition: {current.value} -> {target.value}")


class TaskLock:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else _root() / "task_locks"

    def _path(self, key: str) -> Path:
        safe_key = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
        return self.root / f"{safe_key}.lock"

    def acquire(self, key: str, owner: str, *, stale_after_seconds: float) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        record = {"owner": str(owner), "task_id": str(key), "created_at": time.time()}
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                stale = time.time() - float(old["created_at"]) > stale_after_seconds
                if not stale or not old.get("owner") or old.get("task_id") != str(key):
                    return False
                path.unlink()
            except (OSError, ValueError, KeyError, TypeError):
                return False
            return self.acquire(key, owner, stale_after_seconds=stale_after_seconds)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        return True

    def release(self, key: str, owner: str) -> None:
        path = self._path(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("owner") == str(owner):
                path.unlink()
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return


class StageManifest:
    def __init__(self, root: Path | str | None = None):
        self.root = _root(root) / "staging"

    def _path(self, task_id: str) -> Path:
        return self.root / str(task_id) / "manifest.json"

    def save(self, task_id: str, stage: str, input_hash: str, output_hash: str, metadata: dict[str, Any]) -> None:
        path = self._path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"task_id": str(task_id), "status": "staged", "stages": {}}
        if path.exists():
            data.update(json.loads(path.read_text(encoding="utf-8")))
        data.setdefault("stages", {})[str(stage)] = {
            "input_hash": str(input_hash), "output_hash": str(output_hash), "metadata": dict(metadata),
            "status": "complete", "saved_at": time.time(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


@dataclass(frozen=True)
class RecoveryDecision:
    reusable_stages: tuple[str, ...] = ()
    quarantined: bool = False
    quarantine_path: Path | None = None
    reason: str = ""


def recover_task(task_id: str, root: Path | str | None = None) -> RecoveryDecision:
    base = _root(root)
    manifest_path = base / "staging" / str(task_id) / "manifest.json"
    if not manifest_path.exists():
        return RecoveryDecision(reason="manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stages = manifest["stages"]
        reusable = tuple(name for name, item in stages.items() if _valid_stage(item))
        if len(reusable) != len(stages) or manifest.get("status") != "staged":
            raise ValueError("incomplete_or_invalid_manifest")
        return RecoveryDecision(reusable_stages=reusable)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        source = manifest_path.parent
        target = base / "quarantine" / str(task_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source), str(target))
        return RecoveryDecision(quarantined=True, quarantine_path=target, reason=str(exc))


def _valid_stage(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and item.get("status") == "complete"
        and isinstance(item.get("input_hash"), str)
        and isinstance(item.get("output_hash"), str)
        and isinstance(item.get("metadata"), dict)
    )


def claim_task(key: str, root: Path | str | None = None) -> bool:
    path = _root(root) / "task_claims" / f"{hashlib.sha256(str(key).encode()).hexdigest()}.claim"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(key))
    return True


__all__ = [
    "InvalidTaskTransition", "RecoveryDecision", "StageManifest", "TaskContext", "TaskLock",
    "TaskState", "claim_task", "recover_task", "transition",
]
