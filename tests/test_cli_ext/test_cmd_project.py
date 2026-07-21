# tests/test_cli_ext/test_cmd_project.py
import json
import sys
from pathlib import Path
from unittest.mock import patch


def test_cmd_project_init_creates_project(tmp_path, monkeypatch, capsys):
    """cmd_project_init creates project.json + registers in global registry."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)
    monkeypatch.setattr("src.cli_ext.project_cmd._config_dir", lambda: config_dir, raising=False)

    args = type("Args", (), {"path": str(project_dir), "name": None})()

    project_cmd.cmd_project_init(args)

    # project.json created
    assert (project_dir / ".llm-wiki" / "project.json").exists()
    # Registry has entry
    data = json.loads((config_dir / "registry.json").read_text())
    assert "projects" in data
    assert len(data["projects"]) == 1

    captured = capsys.readouterr()
    assert "Initialized" in captured.out or "myproject" in captured.out


def test_cmd_project_list_shows_registered(tmp_path, monkeypatch, capsys):
    """cmd_project_list shows all registered projects."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    # Pre-populate registry
    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {
            "uuid-a": {"id": "uuid-a", "path": "/p/a", "name": "alpha", "last_opened": 1000, "schema_version": "v2.0"},
            "uuid-b": {"id": "uuid-b", "path": "/p/b", "name": "beta", "last_opened": 2000, "schema_version": "v2.0"},
        }
    }))

    args = type("Args", (), {})()
    project_cmd.cmd_project_list(args)

    captured = capsys.readouterr()
    assert "alpha" in captured.out
    assert "beta" in captured.out
    assert "uuid-a" in captured.out


def test_cmd_project_info(tmp_path, monkeypatch, capsys):
    """cmd_project_info prints full metadata for one project."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-x": {"id": "uuid-x", "path": "/p/x", "name": "x", "last_opened": 1000, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-x"})()
    project_cmd.cmd_project_info(args)

    out = capsys.readouterr().out
    assert "uuid-x" in out
    assert "x" in out
    assert "/p/x" in out


def test_cmd_project_current(tmp_path, monkeypatch, capsys):
    """cmd_project_current prints the resolved project from last_project pointer."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry
    from src.project.context import ProjectContext

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    project_dir = tmp_path / "p"
    project_dir.mkdir()

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    ctx = ProjectContext.from_path(project_dir, name="p")
    monkeypatch.chdir(project_dir)

    args = type("Args", (), {})()
    project_cmd.cmd_project_current(args)

    out = capsys.readouterr().out
    assert ctx.id in out
    assert "p" in out


def test_cmd_project_select(tmp_path, monkeypatch, capsys):
    """cmd_project_select updates last_project pointer."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)
    monkeypatch.setattr("src.cli_ext.project_cmd._last_project_path", lambda: config_dir / "last_project.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-sel": {"id": "uuid-sel", "path": "/p/s", "name": "selected", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "selected"})()
    project_cmd.cmd_project_select(args)

    assert (config_dir / "last_project.json").exists()
    data = json.loads((config_dir / "last_project.json").read_text())
    assert data["id"] == "uuid-sel"
