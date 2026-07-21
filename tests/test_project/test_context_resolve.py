import pytest
from pathlib import Path

from src.project.context import ProjectContext, ProjectNotFoundError
from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry


def test_resolve_by_id(tmp_path, monkeypatch):
    """resolve('uuid-xxx') returns entry from registry."""
    from src.project import paths, registry, context
    from src.project.context import _registry_path

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: config_dir / "registry.json", raising=False)

    project_dir = tmp_path / "p"
    project_dir.mkdir()
    ctx = ProjectContext.from_path(project_dir, name="p")

    resolved = ProjectContext.resolve(ctx.id)
    assert resolved.id == ctx.id


def test_resolve_by_name(tmp_path, monkeypatch):
    """resolve('myproject') finds by name."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)

    project_dir = tmp_path / "p"
    project_dir.mkdir()
    ProjectContext.from_path(project_dir, name="myproject")

    resolved = ProjectContext.resolve("myproject")
    assert resolved.name == "myproject"


def test_resolve_cwd_upward(tmp_path, monkeypatch):
    """resolve(None) + CWD inside project → finds via upward search."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)

    project_dir = tmp_path / "p" / "deep" / "nested"
    project_dir.mkdir(parents=True)
    ProjectContext.from_path(tmp_path / "p", name="p")

    # Pretend CWD is deep inside project
    monkeypatch.chdir(project_dir)
    resolved = ProjectContext.resolve(None)
    assert resolved.id is not None


def test_resolve_raises_with_hint(tmp_path, monkeypatch):
    """resolve() with no project + no CWD project + no last_project → ProjectNotFoundError with hint."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)
    monkeypatch.chdir(tmp_path)  # empty dir, no project

    with pytest.raises(ProjectNotFoundError) as exc:
        ProjectContext.resolve(None)
    assert "No project resolved" in str(exc.value)
    assert "project init" in str(exc.value)
