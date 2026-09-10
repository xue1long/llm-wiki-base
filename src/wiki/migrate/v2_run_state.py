from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...lib.write_hooks import safe_write
from .v2_manifest import CheckpointItem


class RunStateError(ValueError):
    """Raised when persisted migration state cannot be trusted."""


@dataclass
class RunState:
    run_id: str
    project_uuid: str
    source_root: str
    manifest_hash: str
    phase: str = "manifest"
    checkpoint: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    failure_reason: str = ""
    status: str = "running"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def complete_phase(
        self,
        phase: str,
        checkpoint: dict[str, Any] | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        self.phase = phase
        if checkpoint is not None:
            self.checkpoint = checkpoint
        if counts is not None:
            self.counts = counts
        self.status = "phase-complete"
        self.failure_reason = ""

    def pause(self, reason: str) -> None:
        self.status = "paused"
        self.failure_reason = reason

    def fail(self, reason: str) -> None:
        self.status = "failed"
        self.failure_reason = reason


@dataclass(frozen=True)
class RollbackResult:
    run_id: str
    removed_paths: list[str]
    applied: bool


RollbackReport = RollbackResult


def _project_uuid(project_root: Path) -> str:
    path = Path(project_root) / ".llm-wiki" / "project.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("id") or payload["uuid"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RunStateError(f"cannot read project UUID: {path}") from exc


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not run_id:
        raise RunStateError("invalid run id")
    path = Path(run_id)
    if path.name != run_id or run_id in {".", ".."}:
        raise RunStateError("invalid run id")


def run_state_path(project_root: Path, run_id: str) -> Path:
    _validate_run_id(run_id)
    return Path(project_root) / ".index" / "staging" / run_id / "run-state.json"


def save_run_state(project_root: Path, state: RunState) -> Path:
    if _project_uuid(project_root) != state.project_uuid:
        raise RunStateError("project UUID mismatch")
    path = run_state_path(project_root, state.run_id)
    safe_write(path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return path


def load_run_state(
    project_root: Path, run_id: str, manifest_hash: str | None = None
) -> RunState:
    path = run_state_path(project_root, run_id)
    try:
        state = RunState(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RunStateError(f"cannot read run state: {path}") from exc
    if _project_uuid(project_root) != state.project_uuid:
        raise RunStateError("project UUID mismatch")
    if manifest_hash is not None and state.manifest_hash != manifest_hash:
        raise RunStateError("manifest hash mismatch")
    return state


def _read_checkpoint_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RunStateError(f"invalid checkpoint file: {path}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise RunStateError(f"invalid checkpoint record: {path}")
    return rows


def write_checkpoint(path: Path, item: CheckpointItem) -> None:
    path = Path(path)
    if path.name != "migration_progress.jsonl" or not path.parent.name:
        raise RunStateError("invalid checkpoint path")

    rows = _read_checkpoint_rows(path)
    payload = asdict(item)
    key = (item.run_id, item.source_path)
    for index, row in enumerate(rows):
        if (row.get("run_id"), row.get("source_path")) == key:
            rows[index] = payload
            break
    else:
        rows.append(payload)
    safe_write(
        path,
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )


def load_checkpoint(path: Path, run_id: str) -> set[str]:
    return {
        row["source_path"]
        for row in _read_checkpoint_rows(Path(path))
        if row.get("run_id") == run_id
        and row.get("status") == "done"
        and "source_path" in row
    }


def rollback_run(
    project_root: Path, run_id: str, dry_run: bool = True
) -> RollbackResult:
    root = Path(project_root).resolve()
    state = load_run_state(root, run_id)
    staging = run_state_path(root, state.run_id).parent.resolve()
    staging_root = (root / ".index" / "staging").resolve()
    if staging.parent != staging_root:
        raise RunStateError("rollback path outside staging root")
    if staging.is_symlink():
        raise RunStateError("rollback staging path is a symlink")

    removed_paths = [
        str(path)
        for path in sorted(staging.rglob("*"), key=lambda candidate: candidate.as_posix())
        if path.is_file()
    ]
    if not dry_run:
        shutil.rmtree(staging)
    return RollbackResult(
        run_id=run_id, removed_paths=removed_paths, applied=not dry_run
    )
