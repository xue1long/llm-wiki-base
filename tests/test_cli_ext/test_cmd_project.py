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
