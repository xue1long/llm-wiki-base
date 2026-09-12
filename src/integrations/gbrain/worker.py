"""Durable project-level GBrain import job runner."""
from __future__ import annotations

import json
import math
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
from .setup import setup_runtime
from .state import save_runtime_state
from .sync import reconcile_and_sync, run_initial_import
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
    try:
        coverage_pct = float(row.get("embed_coverage_pct", 0.0))
    except (TypeError, ValueError):
        coverage_pct = 0.0
    if not math.isfinite(coverage_pct) or not 0.0 <= coverage_pct <= 100.0:
        coverage_pct = 0.0
    coverage = coverage_pct / 100.0
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
            save_runtime_state(
                root,
                {
                    "status": "failed",
                    "path": validate.get("path"),
                    "error_code": str(validate.get("error_code") or "runtime_not_ready"),
                },
            )
            raise RuntimeError("runtime_not_ready")
        save_runtime_state(
            root,
            {
                "status": "ready",
                "path": str(validate["path"]),
                "origin": str(validate.get("origin") or "worker_preflight"),
                "version": str(validate.get("version") or ""),
                "checks": validate.get("checks") or {},
                "error_code": "",
            },
        )
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


def run_incremental_sync(
    project_root: Path,
    runtime_path: str | Path | None = None,
    *,
    apply_intent: Callable[[str, str, str, str | None], Any] | None = None,
):
    """Reconcile local Wiki changes before a GBrain search."""
    root = Path(project_root)
    config = load_search_config(root)
    runtime = Path(runtime_path) if runtime_path else resolve_runtime(root, load_runtime_config(root)).path
    if runtime is None:
        raise RuntimeError("runtime_not_ready")
    if apply_intent is None:
        from ..searcher.gbrain_mcp import run_mcp_mutation

        def apply_intent(operation, source_id, slug, content):
            return run_mcp_mutation(str(runtime), source_id, operation, slug, content)

    result = reconcile_and_sync(root, apply_intent)
    current = load_search_state(root)
    if result.success:
        snapshot = build_wiki_snapshot(root)
        save_search_state(
            root,
            replace(
                current,
                status=SearchStatus.READY,
                total_pages=len(snapshot),
                synced_pages=len(snapshot),
                failed_pages=0,
                last_error_code="",
            ),
        )
    else:
        save_search_state(
            root,
            replace(current, status=SearchStatus.STALE, failed_pages=len(result.failed), last_error_code="incremental_sync_failed"),
        )
    return result


def run_search_job_for_project(project_id: str, job_id: str) -> dict[str, Any]:
    return run_search_job(resolve_project_root(project_id), job_id)


def run_runtime_setup_job(project_root: Path, job_id: str) -> dict[str, Any]:
    root = Path(project_root)
    job = get_job(root, job_id)
    update_job(root, job_id, status=JobStatus.RUNNING)
    save_runtime_state(root, {"status": "installing", "path": None, "error_code": ""})
    try:
        result = setup_runtime(root, load_runtime_config(root), install=True)
        report = result.to_dict()
        save_runtime_state(root, report)
        if result.status != "ready":
            update_job(root, job_id, status=JobStatus.FAILED, error_code=result.error_code or result.status)
            return {"status": "failed", "jobId": job_id, "error_code": result.error_code or result.status}
        update_job(root, job_id, status=JobStatus.SUCCEEDED)
        return {"status": "ready", "jobId": job_id}
    except Exception:
        save_runtime_state(root, {"status": "failed", "path": None, "error_code": "install_failed"})
        update_job(root, job_id, status=JobStatus.FAILED, error_code="install_failed")
        return {"status": "failed", "jobId": job_id, "error_code": "install_failed"}


def run_runtime_setup_job_for_project(project_id: str, job_id: str) -> dict[str, Any]:
    return run_runtime_setup_job(resolve_project_root(project_id), job_id)


__all__ = [
    "run_runtime_setup_job",
    "run_runtime_setup_job_for_project",
    "run_incremental_sync",
    "run_search_job",
    "run_search_job_for_project",
]
