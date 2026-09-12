"""Explicit, guarded installation of the optional GBrain runtime."""

from __future__ import annotations

import subprocess
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .runtime import (
    DEFAULT_REPOSITORY,
    RuntimeConfig,
    RuntimeStatus,
    RuntimeValidation,
    managed_runtime_path,
    resolve_runtime,
    validate_runtime,
    RuntimeConfigError,
)


@dataclass(frozen=True)
class SetupResult:
    status: str
    path: Path | None = None
    error_code: str = ""
    validation: RuntimeValidation | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.validation is not None:
            report = self.validation.to_dict()
            report["path"] = str(self.path) if self.path else None
            return report
        return {
            "status": self.status,
            "path": str(self.path) if self.path else None,
            "error_code": self.error_code,
        }


def setup_runtime(
    project_root: Path,
    config: RuntimeConfig,
    *,
    install: bool = False,
    timeout: float = 120.0,
    command_runner: Callable[[list[str], Path, float], Any] | None = None,
    version_runner: Callable[[list[str], Path, float], Any] | None = None,
    mcp_probe: Callable[[Path, float], Mapping[str, Any]] | None = None,
) -> SetupResult:
    """Validate an existing runtime or install only after explicit consent."""
    existing = resolve_runtime(project_root, config)
    if existing.status is RuntimeStatus.INVALID_CONFIGURED_RUNTIME:
        return SetupResult(
            "failed", error_code=existing.error_code or "invalid_configured_runtime"
        )
    if existing.path is not None:
        validation = validate_runtime(
            existing,
            config=config,
            expected_version=config.version,
            timeout=timeout,
            runner=version_runner,
            mcp_probe=mcp_probe,
        )
        if validation.status == "ready" or not install or existing.origin != "user:managed":
            return SetupResult(validation.status, validation.path, validation=validation)

    if not install:
        return SetupResult("not_requested", error_code="install_not_requested")
    if config.repository != DEFAULT_REPOSITORY:
        return SetupResult("failed", error_code="repository_not_allowed")
    if not config.ref:
        return SetupResult("failed", error_code="reviewed_ref_required")
    if config.install_mode != "managed":
        return SetupResult("failed", error_code="unsupported_install_mode")

    try:
        target = managed_runtime_path(config)
    except RuntimeConfigError:
        return SetupResult("failed", error_code="unsafe_managed_ref")
    target.parent.mkdir(parents=True, exist_ok=True)
    run = command_runner or _run_command
    with _managed_install_lock(target, timeout) as acquired:
        if not acquired:
            return SetupResult("failed", target, "install_lock_timeout")
        current = resolve_runtime(project_root, config)
        if current.path is not None:
            current_validation = validate_runtime(
                current,
                config=config,
                expected_version=config.version,
                timeout=timeout,
                runner=version_runner,
                mcp_probe=mcp_probe,
            )
            if current_validation.status == "ready":
                return SetupResult("ready", current.path, validation=current_validation)
        temporary = target.with_name(f".{target.name}.install-{uuid.uuid4().hex}")
        try:
            run(["git", "clone", "--no-checkout", config.repository, str(temporary)], project_root, timeout)
            run(["git", "-C", str(temporary), "fetch", "--depth", "1", "origin", config.ref], project_root, timeout)
            run(["git", "-C", str(temporary), "checkout", "--detach", "FETCH_HEAD"], project_root, timeout)
            run(["bun", "install", "--frozen-lockfile", "--ignore-scripts"], temporary, timeout)
            validation = validate_runtime(
                resolve_runtime(temporary, RuntimeConfig(path=str(temporary))),
                config=config,
                expected_version=config.version,
                timeout=timeout,
                runner=version_runner,
                mcp_probe=mcp_probe,
            )
            if validation.status != "ready":
                return SetupResult(validation.status, validation=validation)
            backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
            if target.exists():
                target.replace(backup)
            try:
                temporary.replace(target)
            except Exception:
                if backup.exists():
                    backup.replace(target)
                raise
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return SetupResult("ready", target, validation=validation)
        except (FileNotFoundError, OSError, subprocess.SubprocessError, TimeoutError):
            return SetupResult("failed", error_code="install_failed")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)


@contextmanager
def _managed_install_lock(target: Path, timeout: float):
    lock = target.with_name(f".{target.name}.install.lock")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                lock.mkdir()
                acquired = True
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        yield acquired
    finally:
        if acquired:
            lock.rmdir()


def _run_command(command: list[str], cwd: Path, timeout: float) -> Any:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        shell=False,
    )


__all__ = ["SetupResult", "setup_runtime"]
