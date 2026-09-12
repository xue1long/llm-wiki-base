from __future__ import annotations

import json
from pathlib import Path

from src.integrations.gbrain.runtime import (
    RuntimeConfig,
    RuntimeConfigError,
    RuntimeStatus,
    load_runtime_config,
    managed_runtime_path,
    resolve_runtime,
    validate_runtime,
)
from src.integrations.gbrain.state import load_runtime_state, save_runtime_state


def _make_runtime(root: Path) -> Path:
    runtime = root / "external" / "gbrain"
    (runtime / "src").mkdir(parents=True)
    (runtime / "package.json").write_text("{}", encoding="utf-8")
    (runtime / "src" / "cli.ts").write_text("", encoding="utf-8")
    (runtime / "bun.lock").write_text("", encoding="utf-8")
    return runtime


def test_resolve_prefers_project_relative_runtime(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))

    result = resolve_runtime(tmp_path, RuntimeConfig())

    assert result.status is RuntimeStatus.FOUND
    assert result.path == runtime
    assert result.origin == "project:external/gbrain"


def test_explicit_path_failure_does_not_fall_through(tmp_path):
    project_runtime = _make_runtime(tmp_path)
    config = RuntimeConfig(path=str(tmp_path / "wrong-gbrain"))

    result = resolve_runtime(tmp_path, config)

    assert result.status is RuntimeStatus.INVALID_CONFIGURED_RUNTIME
    assert result.path is None
    assert result.error_code == "invalid_configured_runtime"
    assert result.path != project_runtime


def test_environment_path_is_checked_before_project_path(tmp_path, monkeypatch):
    project_runtime = _make_runtime(tmp_path)
    env_runtime = tmp_path / "env-gbrain"
    _make_runtime_at(env_runtime)
    monkeypatch.setenv("RUFLO_GBRAIN_HOME", str(env_runtime))

    result = resolve_runtime(tmp_path, RuntimeConfig())

    assert result.status is RuntimeStatus.FOUND
    assert result.path == env_runtime
    assert result.origin == "env:RUFLO_GBRAIN_HOME"
    assert result.path != project_runtime


def test_config_round_trips_without_machine_path(tmp_path):
    config_dir = tmp_path / ".llm-wiki"
    config_dir.mkdir()
    (config_dir / "gbrain-runtime.json").write_text(
        json.dumps({"project_relative_path": "external/gbrain", "ref": "abc123"}),
        encoding="utf-8",
    )

    config = load_runtime_config(tmp_path)

    assert config.project_relative_path == "external/gbrain"
    assert config.ref == "abc123"
    assert config.path is None
    assert config.install_mode == "managed"


def test_validate_runtime_uses_argument_arrays_and_mcp_probe(tmp_path):
    runtime = _make_runtime(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def runner(command: list[str], cwd: Path, timeout: float):
        calls.append((command, cwd))
        return "gbrain 0.42.58.0"

    result = validate_runtime(
        resolve_runtime(tmp_path, RuntimeConfig()),
        expected_version="0.42.58.0",
        runner=runner,
        mcp_probe=lambda path, timeout: {"ok": True, "server": "gbrain"},
    )

    assert result.status == "ready"
    assert result.version == "0.42.58.0"
    assert result.checks == {"layout": True, "version": True, "mcp": True}
    assert calls == [(["bun", "run", "src/cli.ts", "--version"], runtime)]


def test_validate_rejects_wrong_version(tmp_path):
    _make_runtime(tmp_path)

    result = validate_runtime(
        resolve_runtime(tmp_path, RuntimeConfig()),
        expected_version="0.42.58.0",
        runner=lambda command, cwd, timeout: "gbrain 0.42.57.0",
        mcp_probe=lambda path, timeout: {"ok": True},
    )

    assert result.status == "failed"
    assert result.error_code == "version_mismatch"
    assert result.checks == {"layout": True, "version": False}


def test_runtime_state_is_written_atomically_and_readable(tmp_path):
    payload = {"status": "ready", "version": "0.42.58.0", "error_code": ""}

    save_runtime_state(tmp_path, payload)

    assert load_runtime_state(tmp_path) == payload
    assert not list((tmp_path / ".index" / "gbrain").glob("*.tmp"))


def test_managed_runtime_path_rejects_ref_escape(tmp_path):
    config = RuntimeConfig(managed_root=str(tmp_path / "managed"), ref="../escape")

    try:
        managed_runtime_path(config)
    except RuntimeConfigError as exc:
        assert str(exc) == "unsafe managed runtime ref"
    else:
        raise AssertionError("path traversal ref must be rejected")


def test_resolve_runtime_fails_closed_before_search_for_unsafe_ref(tmp_path):
    _make_runtime(tmp_path)

    result = resolve_runtime(tmp_path, RuntimeConfig(ref="../../escape"))

    assert result.status is RuntimeStatus.INVALID_CONFIGURED_RUNTIME
    assert result.error_code == "unsafe_managed_ref"
    assert result.path is None


def _make_runtime_at(runtime: Path) -> Path:
    (runtime / "src").mkdir(parents=True)
    (runtime / "package.json").write_text("{}", encoding="utf-8")
    (runtime / "src" / "cli.ts").write_text("", encoding="utf-8")
    (runtime / "bun.lock").write_text("", encoding="utf-8")
    return runtime
