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


def test_cmd_project_import(tmp_path, monkeypatch, capsys):
    """cmd_project_import registers an existing KB at given path."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "external_kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid-ext", "name": "external", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    args = type("Args", (), {"path": str(kb), "name": None})()
    project_cmd.cmd_project_import(args)

    from src.project.registry import GlobalRegistryStore
    entry = GlobalRegistryStore.by_id("uuid-ext")
    assert entry is not None
    assert entry.name == "external"


def test_cmd_project_forget_removes_registry_entry(tmp_path, monkeypatch, capsys):
    """cmd_project_forget removes entry from registry but not from disk."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-f": {"id": "uuid-f", "path": "/p/f", "name": "f", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-f", "delete_data": False})()
    project_cmd.cmd_project_forget(args)

    from src.project.registry import GlobalRegistryStore
    assert GlobalRegistryStore.by_id("uuid-f") is None
    captured = capsys.readouterr()
    assert "removed from registry" in captured.out


def test_cmd_project_forget_refuses_when_id_used_by_other(tmp_path, monkeypatch, capsys):
    """cmd_project_forget refuses to delete project.json if --delete-data and path no longer registered."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "kb_real"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {
            "uuid-r": {"id": "uuid-r", "path": str(kb), "name": "r", "last_opened": 0, "schema_version": "v2.0"},
            "uuid-r2": {"id": "uuid-r2", "path": str(kb), "name": "r2", "last_opened": 0, "schema_version": "v2.0"},
        }
    }))

    args = type("Args", (), {"id_or_name": "uuid-r", "delete_data": True})()
    try:
        project_cmd.cmd_project_forget(args)
    except SystemExit:
        pass

    assert kb.exists()
    out = capsys.readouterr().err
    assert "refusing" in out.lower() or "error" in out.lower()


def test_cmd_project_rename(tmp_path, monkeypatch, capsys):
    """cmd_project_rename updates name in registry + project.json."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "kb_rename"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid-rn", "name": "old_name", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-rn": {"id": "uuid-rn", "path": str(kb), "name": "old_name", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-rn", "new_name": "new_name"})()
    project_cmd.cmd_project_rename(args)

    from src.project.registry import GlobalRegistryStore
    entry = GlobalRegistryStore.by_id("uuid-rn")
    assert entry.name == "new_name"
    data = json.loads((kb / ".llm-wiki" / "project.json").read_text())
    assert data["name"] == "new_name"


def test_cmd_project_discover_finds_and_registers(tmp_path, monkeypatch, capsys):
    """cmd_project_discover runs auto_register_on_first_run."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry, discovery
    from src.project.registry import GlobalRegistryStore

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "kb_discovered").mkdir()
    (docs / "kb_discovered" / ".index").mkdir()
    (docs / "kb_discovered" / ".index" / "schema_version").write_text("v2.0")

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr(discovery, "DEFAULT_SEARCH_PATHS", [docs])

    args = type("Args", (), {})()
    project_cmd.cmd_project_discover(args)

    out = capsys.readouterr().out
    assert "kb_discovered" in out
    entry = GlobalRegistryStore.by_path(docs / "kb_discovered")
    assert entry is not None
