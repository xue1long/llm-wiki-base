"""Project configuration and durable job API for GBrain search."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from ...lib.time import now_ms
from .types import GBrainJob, JobStatus, SearchConfig, SearchState


class GBrainProjectError(ValueError):
    """Fail-closed project configuration or ownership error."""


def _gbrain_dir(root: Path) -> Path:
    return Path(root) / ".index" / "gbrain"


def _config_path(root: Path) -> Path:
    return Path(root) / ".llm-wiki" / "gbrain-search.json"


def _state_path(root: Path) -> Path:
    return _gbrain_dir(root) / "search-state.json"


def _jobs_path(root: Path) -> Path:
    return _gbrain_dir(root) / "jobs.json"


def _project_lock_path(root: Path) -> Path:
    return _gbrain_dir(root) / "project.lock"


@contextmanager
def project_lock(project_root: Path, timeout: float = 30.0) -> Iterator[None]:
    """Acquire a cross-process per-project lock for GBrain state changes."""
    path = _project_lock_path(Path(project_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("gbrain project lock timeout")
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GBrainProjectError(f"invalid_gbrain_state:{path.name}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _project_identity(root: Path) -> tuple[str, str]:
    path = Path(root) / ".llm-wiki" / "project.json"
    raw = _read_json(path, None)
    if not isinstance(raw, dict) or not raw.get("id"):
        raise GBrainProjectError("invalid_project_identity")
    return str(raw["id"]), str(raw.get("name") or Path(root).name)


def _default_config(root: Path) -> SearchConfig:
    project_id, name = _project_identity(root)
    digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:12]
    return SearchConfig(
        source_id=f"ruflo-{digest}",
        source_name=f"ruflo-kb/{name}",
    )


def load_search_config(project_root: Path) -> SearchConfig:
    root = Path(project_root)
    raw = _read_json(_config_path(root), None)
    if raw is None:
        return _default_config(root)
    if not isinstance(raw, dict):
        raise GBrainProjectError("invalid_search_config")
    return SearchConfig.from_dict(raw)


def ensure_search_config(project_root: Path) -> SearchConfig:
    root = Path(project_root)
    path = _config_path(root)
    with project_lock(root):
        if path.exists():
            return load_search_config(root)
        config = _default_config(root)
        _write_json(path, config.to_dict())
        return config


def save_search_config(project_root: Path, config: SearchConfig) -> None:
    with project_lock(Path(project_root)):
        _write_json(_config_path(Path(project_root)), config.to_dict())


def load_search_state(project_root: Path) -> SearchState:
    root = Path(project_root)
    raw = _read_json(_state_path(root), None)
    if raw is None:
        return SearchState(config_epoch=load_search_config(root).config_epoch)
    if not isinstance(raw, dict):
        raise GBrainProjectError("invalid_search_state")
    return SearchState.from_dict(raw)


def save_search_state(project_root: Path, state: SearchState) -> None:
    with project_lock(Path(project_root)):
        _write_json(_state_path(Path(project_root)), state.to_dict())


def validate_source_ownership(project_root: Path, source_id: str) -> bool:
    config = load_search_config(Path(project_root))
    if config.source_id != source_id:
        raise GBrainProjectError("source_ownership_conflict")
    return True


def load_jobs(project_root: Path) -> list[GBrainJob]:
    raw = _read_json(_jobs_path(Path(project_root)), [])
    if not isinstance(raw, list):
        raise GBrainProjectError("invalid_job_store")
    return [GBrainJob.from_dict(item) for item in raw if isinstance(item, dict)]


def enqueue_job(project_root: Path, kind: str) -> GBrainJob:
    root = Path(project_root)
    config = load_search_config(root)
    with project_lock(root):
        jobs = load_jobs(root)
        active = {JobStatus.QUEUED, JobStatus.RUNNING}
        for job in reversed(jobs):
            if job.kind == kind and job.config_epoch == config.config_epoch and job.status in active:
                return job
        now = now_ms()
        job = GBrainJob(
            id=f"gbj-{uuid.uuid4().hex[:16]}",
            kind=kind,
            status=JobStatus.QUEUED,
            config_epoch=config.config_epoch,
            created_at=now,
            updated_at=now,
        )
        _write_json(_jobs_path(root), [*map(GBrainJob.to_dict, jobs), job.to_dict()])
        return job


def get_job(project_root: Path, job_id: str) -> GBrainJob:
    for job in load_jobs(Path(project_root)):
        if job.id == job_id:
            return job
    raise GBrainProjectError("job_not_found")


def update_job(
    project_root: Path,
    job_id: str,
    *,
    status: JobStatus,
    error_code: str = "",
) -> GBrainJob:
    root = Path(project_root)
    with project_lock(root):
        jobs = load_jobs(root)
        for index, job in enumerate(jobs):
            if job.id == job_id:
                updated = GBrainJob(
                    id=job.id,
                    kind=job.kind,
                    status=status,
                    config_epoch=job.config_epoch,
                    created_at=job.created_at,
                    updated_at=now_ms(),
                    error_code=error_code,
                )
                jobs[index] = updated
                _write_json(_jobs_path(root), [item.to_dict() for item in jobs])
                return updated
    raise GBrainProjectError("job_not_found")


__all__ = [
    "GBrainProjectError",
    "enqueue_job",
    "ensure_search_config",
    "get_job",
    "load_jobs",
    "load_search_config",
    "load_search_state",
    "project_lock",
    "save_search_config",
    "save_search_state",
    "update_job",
    "validate_source_ownership",
]
