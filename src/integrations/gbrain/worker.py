"""Durable project-level GBrain import job runner."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .api import (
    build_wiki_snapshot,
    get_job,
    load_search_config,
    load_search_state,
    save_manifest,
    save_search_state,
    update_job,
)
from .runtime import load_runtime_config, resolve_runtime, validate_runtime
from .service import resolve_project_root
from .sync import run_initial_import
from .types import JobStatus, SearchState, SearchStatus


def _default_runtime_validator(root: Path) -> dict[str, Any]:
    config = load_runtime_config(root)
    validation = validate_runtime(
        resolve_runtime(root, config),
        config=config,
        expected_version=config.version or None,
    )
    return {"ready": validation.status == "ready", "path": str(validation.path) if validation.path else None}


def _default_importer(root: Path, config, runtime_path: str) -> None:
    run_initial_import(root, config, Path(runtime_path))


def _default_status_probe(root: Path, config) -> dict[str, float]:
    runtime = load_runtime_config(root)
    resolution = resolve_runtime(root, runtime)
    if resolution.path is None:
        return {"embedding_coverage": 0.0, "path_mapping_coverage": 0.0}
    env = os.environ.copy()
    env["GBRAIN_SOURCE"] = config.source_id
    result = subprocess.run(
        ["bun", "run", "src/cli.ts", "sources", "status", "--json"],
        cwd=resolution.path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    payload = json.loads(result.stdout)
    rows = payload.get("sources", []) if isinstance(payload, dict) else payload
    row = next((item for item in rows if item.get("source_id") == config.source_id), None)
    if not row:
        return {"embedding_coverage": 0.0, "path_mapping_coverage": 0.0}
    coverage = float(row.get("embedding_coverage_pct", 0.0)) / 100.0
    return {"embedding_coverage": coverage, "path_mapping_coverage": 1.0}


def run_search_job(
    project_root: Path,
    job_id: str,
    *,
    runtime_validator: Callable[[Path], dict[str, Any]] | None = None,
    importer: Callable[[Path, Any, str], None] | None = None,
    status_probe: Callable[[Path, Any], dict[str, float]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    job = get_job(root, job_id)
    config = load_search_config(root)
    if job.config_epoch != config.config_epoch or (job.kind == "enable" and not config.enabled):
        update_job(root, job_id, status=JobStatus.CANCELLED, error_code="stale_job")
        return {"status": "cancelled", "error_code": "stale_job"}

    update_job(root, job_id, status=JobStatus.RUNNING)
    save_search_state(
        root,
        replace(load_search_state(root), status=SearchStatus.SYNCING, job_id=job_id),
    )
    try:
        validate = (runtime_validator or _default_runtime_validator)(root)
        if not validate.get("ready") or not validate.get("path"):
            raise RuntimeError("runtime_not_ready")
        (importer or _default_importer)(root, config, str(validate["path"]))
        snapshot = build_wiki_snapshot(root)
        save_manifest(root, snapshot)
        metrics = (status_probe or _default_status_probe)(root, config)
        coverage = float(metrics.get("embedding_coverage", 0.0))
        mapping = float(metrics.get("path_mapping_coverage", 0.0))
        if coverage < 1.0:
            raise RuntimeError("embedding_incomplete")
        if mapping < 1.0:
            raise RuntimeError("path_mapping_incomplete")
        latest = load_search_config(root)
        if latest.config_epoch != job.config_epoch or (job.kind == "enable" and not latest.enabled):
            update_job(root, job_id, status=JobStatus.CANCELLED, error_code="stale_job")
            return {"status": "cancelled", "error_code": "stale_job"}
        save_search_state(
            root,
            replace(
                load_search_state(root),
                status=SearchStatus.READY,
                config_epoch=latest.config_epoch,
                job_id=job_id,
                total_pages=len(snapshot),
                synced_pages=len(snapshot),
                failed_pages=0,
                embedding_coverage=coverage,
                path_mapping_coverage=mapping,
                last_error_code="",
            ),
        )
        update_job(root, job_id, status=JobStatus.SUCCEEDED)
        return {"status": "ready", "jobId": job_id}
    except RuntimeError as exc:
        error_code = str(exc)
    except Exception:
        error_code = "sync_failed"
    save_search_state(
        root,
        replace(load_search_state(root), status=SearchStatus.FAILED, job_id=job_id, last_error_code=error_code),
    )
    update_job(root, job_id, status=JobStatus.FAILED, error_code=error_code)
    return {"status": "failed", "jobId": job_id, "error_code": error_code}


def run_search_job_for_project(project_id: str, job_id: str) -> dict[str, Any]:
    return run_search_job(resolve_project_root(project_id), job_id)


__all__ = ["run_search_job", "run_search_job_for_project"]
