# tests/test_project/test_context.py

from src.project.context import ProjectContext
from src.project.registry import GlobalRegistryStore


def test_from_path_creates_new_project(tmp_path, monkeypatch):
    """from_path() on fresh dir creates project.json + registers in registry."""
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")

    project_dir = tmp_path / "my_kb"
    project_dir.mkdir()

    ctx = ProjectContext.from_path(project_dir, name="my_kb")

    assert ctx.id is not None
    assert len(ctx.id) == 36
    assert ctx.name == "my_kb"
    assert ctx.path == project_dir.resolve()
    assert ctx.schema_version == "v2.0"

    # Registered in global registry
    entry = GlobalRegistryStore.by_id(ctx.id)
    assert entry is not None
    assert entry.name == "my_kb"


def test_from_path_returns_existing(tmp_path, monkeypatch):
    """from_path() on existing project returns same UUID."""
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")

    project_dir = tmp_path / "existing_kb"
    project_dir.mkdir()

    first = ProjectContext.from_path(project_dir, name="existing_kb")
    second = ProjectContext.from_path(project_dir, name="existing_kb")
    assert first.id == second.id
