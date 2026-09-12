"""Project-level GBrain search lifecycle service."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ...lib.project import resolve_project
from ...lib.time import now_ms
from .api import (
    enqueue_job,
    ensure_search_config,
    get_job,
    load_search_config,
    load_search_state,
    save_search_config,
    save_search_state,
)
from .runtime import load_runtime_config, resolve_runtime, validate_runtime
from .state import load_runtime_state, save_runtime_state
from .types import SearchStatus


def resolve_project_root(project_id: str) -> Path:
    context, _paths = resolve_project(project_id, by_id_only=True)
    return context.path


def get_search_status(project_id: str) -> dict:
    root = resolve_project_root(project_id)
    config = ensure_search_config(root)
    state = load_search_state(root)
    ready = config.enabled and state.status is SearchStatus.READY
    return {
        "enabled": config.enabled,
        "source_id": config.source_id,
        "source_name": config.source_name,
        "source_path": config.source_path,
        "config_epoch": config.config_epoch,
        "status": state.status.value,
        "ready": ready,
        "backend": "gbrain" if ready else "local",
        "job_id": state.job_id,
        "total_pages": state.total_pages,
        "synced_pages": state.synced_pages,
        "failed_pages": state.failed_pages,
        "embedding_coverage": state.embedding_coverage,
        "path_mapping_coverage": state.path_mapping_coverage,
        "last_error_code": state.last_error_code,
    }


def get_runtime_status(project_id: str) -> dict:
    root = resolve_project_root(project_id)
    stored = load_runtime_state(root)
    if stored.get("status") == "installing":
        return stored
    config = load_runtime_config(root)
    resolution = resolve_runtime(root, config)
    validation = validate_runtime(resolution, config=config, expected_version=config.version or None)
    report = validation.to_dict()
    save_runtime_state(root, report)
    return report


def setup_runtime_job(project_id: str, *, confirm: bool) -> dict:
    if not confirm:
        raise ValueError("confirmation_required")
    root = resolve_project_root(project_id)
    ensure_search_config(root)
    job = enqueue_job(root, "setup")
    return {"status": "queued", "jobId": job.id}


def enable_search(project_id: str, *, confirm: bool) -> dict:
    if not confirm:
        raise ValueError("confirmation_required")
    root = resolve_project_root(project_id)
    config = ensure_search_config(root)
    state = load_search_state(root)
    if config.enabled and state.status is SearchStatus.READY:
        return {"status": "ready", "jobId": state.job_id}
    if not config.enabled:
        config = replace(config, enabled=True, consent_at=now_ms())
        save_search_config(root, config)
    job = enqueue_job(root, "enable")
    save_search_state(
        root,
        replace(state, status=SearchStatus.QUEUED, config_epoch=config.config_epoch, job_id=job.id),
    )
    return {"status": "queued", "jobId": job.id}


def disable_search(project_id: str) -> dict:
    root = resolve_project_root(project_id)
    config = ensure_search_config(root)
    config = replace(config, enabled=False, config_epoch=config.config_epoch + 1)
    save_search_config(root, config)
    save_search_state(
        root,
        replace(load_search_state(root), status=SearchStatus.DISABLED, config_epoch=config.config_epoch),
    )
    return {"status": "disabled", "backend": "local"}


def rebuild_search(project_id: str, *, confirm: bool) -> dict:
    if not confirm:
        raise ValueError("confirmation_required")
    root = resolve_project_root(project_id)
    config = ensure_search_config(root)
    config = replace(config, config_epoch=config.config_epoch + 1)
    save_search_config(root, config)
    job = enqueue_job(root, "rebuild")
    save_search_state(
        root,
        replace(load_search_state(root), status=SearchStatus.QUEUED, config_epoch=config.config_epoch, job_id=job.id),
    )
    return {"status": "queued", "jobId": job.id}


def get_search_job(project_id: str, job_id: str) -> dict:
    return get_job(resolve_project_root(project_id), job_id).to_dict()


__all__ = [
    "disable_search",
    "enable_search",
    "get_search_job",
    "get_search_status",
    "get_runtime_status",
    "rebuild_search",
    "resolve_project_root",
    "setup_runtime_job",
]
