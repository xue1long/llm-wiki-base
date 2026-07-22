"""Tests for src.services.projects — registry query for projects list/get."""
from src.services import projects as projects_service


def test_list_projects_empty(monkeypatch, tmp_path):
    """list_projects returns [] when the global registry is empty."""
    from src.project.registry import GlobalRegistryStore
    from src.project import paths as project_paths

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    result = projects_service.list_projects()
    assert result == {"projects": []}


def test_list_projects_includes_metadata(monkeypatch, tmp_path):
    """list_projects returns id/name/path/schema_version for each entry."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    from src.project import paths as project_paths

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u1", name="p1", path=str(tmp_path / "p1"),
        last_opened=1000, schema_version="v2.0",
    ))

    result = projects_service.list_projects()
    assert len(result["projects"]) == 1
    p = result["projects"][0]
    assert p["id"] == "u1"
    assert p["name"] == "p1"
    assert p["schema_version"] == "v2.0"


def test_get_project_by_id(monkeypatch, tmp_path):
    """get_project returns the entry's dict when found by id."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    from src.project import paths as project_paths

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u2", name="p2", path=str(tmp_path / "p2"),
        last_opened=2000, schema_version="v2.0",
    ))

    result = projects_service.get_project("u2")
    assert result["id"] == "u2"
    assert result["name"] == "p2"


def test_get_project_by_name(monkeypatch, tmp_path):
    """get_project falls back to name lookup when id misses."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    from src.project import paths as project_paths

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u3", name="my-name", path=str(tmp_path / "p3"),
        last_opened=3000, schema_version="v2.0",
    ))

    result = projects_service.get_project("my-name")
    assert result["id"] == "u3"


def test_get_project_not_found(monkeypatch, tmp_path):
    """get_project raises ProjectNotFound when neither id nor name matches."""
    from src.project.registry import GlobalRegistryStore
    from src.project import paths as project_paths

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    with __import__("pytest").raises(projects_service.ProjectNotFound):
        projects_service.get_project("does-not-exist")
