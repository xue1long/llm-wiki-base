"""Discover and validate an approved local GBrain runtime."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Mapping


DEFAULT_REPOSITORY = "https://github.com/garrytan/gbrain.git"
_VERSION_RE = re.compile(r"(?:gbrain\s+)?v?(\d+(?:\.\d+){2,3})", re.IGNORECASE)
_REQUIRED_FILES = ("package.json", "src/cli.ts")
_LOCK_FILES = ("bun.lock", "bun.lockb")


class RuntimeStatus(str, Enum):
    MISSING = "missing"
    FOUND = "found"
    INVALID_CONFIGURED_RUNTIME = "invalid_configured_runtime"


@dataclass(frozen=True)
class RuntimeConfig:
    repository: str = DEFAULT_REPOSITORY
    ref: str = ""
    version: str = ""
    path: str | None = None
    project_relative_path: str = "external/gbrain"
    install_mode: str = "managed"
    managed_root: str | None = None
    auto_install: bool = False
    allow_path_command: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RuntimeConfig":
        return cls(
            repository=str(raw.get("repository") or DEFAULT_REPOSITORY),
            ref=str(raw.get("ref") or ""),
            version=str(raw.get("version") or ""),
            path=str(raw["path"]) if raw.get("path") else None,
            project_relative_path=str(
                raw.get("project_relative_path") or "external/gbrain"
            ),
            install_mode=str(raw.get("install_mode") or "managed"),
            managed_root=str(raw["managed_root"]) if raw.get("managed_root") else None,
            auto_install=bool(raw.get("auto_install", False)),
            allow_path_command=bool(raw.get("allow_path_command", False)),
        )


@dataclass(frozen=True)
class RuntimeResolution:
    status: RuntimeStatus
    path: Path | None = None
    origin: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class RuntimeValidation:
    status: str
    path: Path | None
    origin: str
    version: str = ""
    checks: dict[str, bool] | None = None
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": str(self.path) if self.path else None,
            "origin": self.origin,
            "version": self.version,
            "checks": self.checks or {},
            "error_code": self.error_code,
        }


class RuntimeConfigError(ValueError):
    """Raised when the project runtime configuration is malformed."""


def runtime_config_path(project_root: Path) -> Path:
    return Path(project_root) / ".llm-wiki" / "gbrain-runtime.json"


def load_runtime_config(project_root: Path) -> RuntimeConfig:
    path = runtime_config_path(Path(project_root))
    if not path.exists():
        return RuntimeConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"invalid GBrain runtime config: {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeConfigError(f"GBrain runtime config must be an object: {path}")
    return RuntimeConfig.from_dict(raw)


def resolve_runtime(
    project_root: Path,
    config: RuntimeConfig | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeResolution:
    root = Path(project_root).resolve()
    config = config or load_runtime_config(root)
    env = environ or os.environ

    if config.path is not None:
        return _resolve_explicit(Path(config.path), root, "config:path")

    env_path = env.get("RUFLO_GBRAIN_HOME")
    if env_path:
        return _resolve_explicit(Path(env_path), root, "env:RUFLO_GBRAIN_HOME")

    candidates = [
        (root / config.project_relative_path, f"project:{config.project_relative_path}"),
        (root / ".external" / "gbrain", "project:.external/gbrain"),
        (_managed_runtime_root(config, env), "user:managed"),
    ]
    for candidate, origin in candidates:
        if candidate.is_dir():
            return RuntimeResolution(RuntimeStatus.FOUND, candidate, origin)
    return RuntimeResolution(RuntimeStatus.MISSING)


def validate_runtime(
    resolution: RuntimeResolution,
    *,
    config: RuntimeConfig | None = None,
    expected_version: str | None = None,
    timeout: float = 5.0,
    runner: Callable[[list[str], Path, float], Any] | None = None,
    mcp_probe: Callable[[Path, float], Mapping[str, Any]] | None = None,
) -> RuntimeValidation:
    if resolution.status is not RuntimeStatus.FOUND or resolution.path is None:
        return RuntimeValidation(
            status=resolution.status.value,
            path=None,
            origin=resolution.origin,
            checks={},
            error_code=resolution.error_code or resolution.status.value,
        )

    path = resolution.path
    layout_ok = all((path / name).is_file() for name in _REQUIRED_FILES) and any(
        (path / name).is_file() for name in _LOCK_FILES
    )
    checks: dict[str, bool] = {"layout": layout_ok}
    if not layout_ok:
        return RuntimeValidation(
            status="failed",
            path=path,
            origin=resolution.origin,
            checks=checks,
            error_code="runtime_layout_invalid",
        )

    command_runner = runner or _run_version
    try:
        output = command_runner(["bun", "run", "src/cli.ts", "--version"], path, timeout)
    except FileNotFoundError:
        checks["version"] = False
        return RuntimeValidation(
            status="failed",
            path=path,
            origin=resolution.origin,
            checks=checks,
            error_code="bun_missing",
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        checks["version"] = False
        return RuntimeValidation(
            status="failed",
            path=path,
            origin=resolution.origin,
            checks=checks,
            error_code="version_probe_failed",
        )

    version = _parse_version(output)
    wanted = expected_version or (config.version if config else "")
    version_ok = bool(version) and (not wanted or version == wanted)
    checks["version"] = version_ok
    if not version_ok:
        return RuntimeValidation(
            status="failed",
            path=path,
            origin=resolution.origin,
            version=version,
            checks=checks,
            error_code="version_mismatch" if version else "version_unparseable",
        )

    probe = mcp_probe or _probe_mcp_initialize
    try:
        probe_result = probe(path, timeout)
    except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
        checks["mcp"] = False
        return RuntimeValidation(
            status="failed",
            path=path,
            origin=resolution.origin,
            version=version,
            checks=checks,
            error_code="mcp_probe_failed",
        )
    checks["mcp"] = bool(probe_result.get("ok"))
    return RuntimeValidation(
        status="ready" if checks["mcp"] else "failed",
        path=path,
        origin=resolution.origin,
        version=version,
        checks=checks,
        error_code="" if checks["mcp"] else "mcp_probe_failed",
    )


def _resolve_explicit(path: Path, root: Path, origin: str) -> RuntimeResolution:
    candidate = path if path.is_absolute() else root / path
    if candidate.is_dir():
        return RuntimeResolution(RuntimeStatus.FOUND, candidate.resolve(), origin)
    return RuntimeResolution(
        RuntimeStatus.INVALID_CONFIGURED_RUNTIME,
        origin=origin,
        error_code="invalid_configured_runtime",
    )


def _managed_runtime_root(config: RuntimeConfig, env: Mapping[str, str]) -> Path:
    if config.managed_root:
        return Path(config.managed_root).expanduser()
    if os.name == "nt":
        base = Path(env.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    root = base / "ruflo-kb" / "external" / "gbrain"
    return root / (config.ref or "current")


def managed_runtime_path(
    config: RuntimeConfig, environ: Mapping[str, str] | None = None
) -> Path:
    """Return the user-managed install target without creating it."""
    return _managed_runtime_root(config, environ or os.environ)


def _run_version(command: list[str], cwd: Path, timeout: float) -> str:
    if shutil.which(command[0]) is None:
        raise FileNotFoundError(command[0])
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return f"{completed.stdout}\n{completed.stderr}"


def _probe_mcp_initialize(path: Path, timeout: float) -> Mapping[str, Any]:
    if shutil.which("bun") is None:
        raise FileNotFoundError("bun")
    process = subprocess.Popen(
        ["bun", "run", "src/cli.ts", "serve"],
        cwd=path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        shell=False,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ruflo-kb", "version": "1"},
            },
        }
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        lines: Queue[str] = Queue()
        reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            line = lines.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError("MCP initialize timed out") from exc
        if not line:
            raise ValueError("MCP server closed stdout")
        response = json.loads(line)
        return {"ok": bool(response.get("result")) and not response.get("error")}
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=timeout)


def _parse_version(output: Any) -> str:
    text = output if isinstance(output, str) else str(output)
    match = _VERSION_RE.search(text)
    return match.group(1) if match else ""


__all__ = [
    "RuntimeConfig",
    "RuntimeConfigError",
    "RuntimeResolution",
    "RuntimeStatus",
    "RuntimeValidation",
    "load_runtime_config",
    "managed_runtime_path",
    "resolve_runtime",
    "runtime_config_path",
    "validate_runtime",
]
