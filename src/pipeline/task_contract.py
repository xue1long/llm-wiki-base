"""Small, filesystem-backed contract for task identity and recovery."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def _root(root: Path | str | None = None) -> Path:
    return Path(root or os.environ.get("RUFLO_TASK_STATE_DIR") or Path.cwd() / ".index")


def _safe_component(value: str) -> str:
    value = str(value)
    if value and value not in {".", ".."} and re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return value
    return "task-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_path": str(self.source_path),
            "source_hash": self.source_hash,
            "template_version": self.template_version,
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }


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
        record = {"owner": str(owner), "run_token": str(owner), "task_id": str(key), "created_at": time.time()}
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        return True

    def reclaim(self, key: str, recovery_owner: str, *, stale_after_seconds: float) -> bool:
        """Remove one verified stale lock; normal acquisition never reclaims."""
        path = self._path(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            stale = time.time() - float(record["created_at"]) > stale_after_seconds
            if not stale or not record.get("owner") or record.get("task_id") != str(key):
                return False
            path.unlink()
            return True
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
            return False

    def release(self, key: str, owner: str) -> None:
        path = self._path(key)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("owner") == str(owner):
                path.unlink()
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return


class StageManifest:
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, root: Path | str | None = None):
        self.root = _root(root) / "staging"

    def _path(self, task_id: str) -> Path:
        return self.root / _safe_component(task_id) / "manifest.json"

    def _lock(self, path: Path) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(str(path), threading.RLock())

    def save(self, task_id: str, stage: str, input_hash: str, output_hash: str, metadata: dict[str, Any]) -> None:
        path = self._path(task_id)
        with self._lock(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {"task_id": str(task_id), "status": "staged", "stages": {}}
            if path.exists():
                data.update(json.loads(path.read_text(encoding="utf-8")))
            context = metadata.get("task_context")
            if isinstance(context, dict):
                data["context"] = dict(context)
            data.setdefault("stages", {})[str(stage)] = {
                "input_hash": str(input_hash), "output_hash": str(output_hash), "metadata": dict(metadata),
                "status": "complete", "saved_at": time.time(),
            }
            if stage == "committed":
                data["status"] = "committed"
            elif stage == "failed":
                data["status"] = "failed"
            fd, tmp_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                os.replace(tmp_name, path)
            finally:
                Path(tmp_name).unlink(missing_ok=True)


@dataclass(frozen=True)
class RecoveryDecision:
    reusable_stages: tuple[str, ...] = ()
    quarantined: bool = False
    quarantine_path: Path | None = None
    reason: str = ""
    completed: bool = False


def recover_task(
    task_id: str, root: Path | str | None = None, *,
    expected_context: TaskContext | dict[str, Any] | None = None,
) -> RecoveryDecision:
    base = _root(root)
    manifest_path = base / "staging" / _safe_component(task_id) / "manifest.json"
    if not manifest_path.exists():
        return RecoveryDecision(reason="manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stages = manifest["stages"]
        if manifest.get("task_id") != str(task_id):
            raise ValueError("task_id_mismatch")
        if expected_context is not None:
            expected = expected_context.to_dict() if isinstance(expected_context, TaskContext) else dict(expected_context)
            actual = manifest.get("context")
            stable_keys = ("task_id", "source_path", "source_hash", "template_version", "contract_version")
            if not isinstance(actual, dict) or any(actual.get(k) != expected.get(k) for k in stable_keys):
                raise ValueError("task_context_mismatch")
        reusable = tuple(name for name, item in stages.items() if _valid_stage(item))
        if manifest.get("status") == "committed":
            return RecoveryDecision(reusable_stages=reusable, completed=True)
        if len(reusable) != len(stages) or manifest.get("status") != "staged":
            raise ValueError("incomplete_or_invalid_manifest")
        return RecoveryDecision(reusable_stages=reusable)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        source = manifest_path.parent
        target = base / "quarantine" / _safe_component(task_id)
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
    scope = (str(_root(root).resolve()), str(key))
    with _claim_lock:
        if scope in _claimed_tasks:
            return False
        _claimed_tasks.add(scope)
        return True


def release_task_claim(key: str, root: Path | str | None = None) -> None:
    with _claim_lock:
        _claimed_tasks.discard((str(_root(root).resolve()), str(key)))


_claim_lock = threading.Lock()
_claimed_tasks: set[tuple[str, str]] = set()


__all__ = [
    "InvalidTaskTransition", "RecoveryDecision", "StageManifest", "TaskContext", "TaskLock",
    "TaskState", "claim_task", "recover_task", "release_task_claim", "transition",
]
