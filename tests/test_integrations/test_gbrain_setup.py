from __future__ import annotations

from pathlib import Path

from src.integrations.gbrain.runtime import RuntimeConfig
from src.integrations.gbrain.setup import setup_runtime


def test_setup_requires_reviewed_ref_before_network(tmp_path) -> None:
    called = False

    def runner(command, cwd, timeout):
        nonlocal called
        called = True

    result = setup_runtime(tmp_path, RuntimeConfig(), install=True, command_runner=runner)

    assert result.status == "failed"
    assert result.error_code == "reviewed_ref_required"
    assert called is False


def test_setup_does_not_fall_through_from_invalid_explicit_path(tmp_path) -> None:
    config = RuntimeConfig(path=str(tmp_path / "missing"), ref="reviewed-commit")

    result = setup_runtime(tmp_path, config, install=True)

    assert result.status == "failed"
    assert result.error_code == "invalid_configured_runtime"


def test_setup_uses_isolated_clone_and_promotes_only_when_ready(tmp_path, monkeypatch) -> None:
    config = RuntimeConfig(ref="reviewed-commit", version="0.42.58.0")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))
    commands: list[list[str]] = []

    def runner(command, cwd, timeout):
        commands.append(command)
        if command[0] == "git" and command[1] == "clone":
            target = Path(command[-1])
            (target / "src").mkdir(parents=True)
            (target / "package.json").write_text("{}", encoding="utf-8")
            (target / "src" / "cli.ts").write_text("", encoding="utf-8")
            (target / "bun.lock").write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "src.integrations.gbrain.setup.validate_runtime",
        lambda *args, **kwargs: _ready_validation(args[0].path),
    )

    result = setup_runtime(
        tmp_path,
        config,
        install=True,
        command_runner=runner,
    )

    assert result.status == "ready", result
    assert result.path is not None and result.path.exists()
    assert commands[0][:3] == ["git", "clone", "--no-checkout"]
    assert commands[1][0:4] == ["git", "-C", commands[1][2], "fetch"]
    assert commands[3][:2] == ["bun", "install"]


def _ready_validation(path: Path):
    from src.integrations.gbrain.runtime import RuntimeValidation

    return RuntimeValidation("ready", path, "config:path", "0.42.58.0", {"layout": True, "version": True, "mcp": True})
