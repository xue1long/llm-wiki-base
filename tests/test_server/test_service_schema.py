"""Tests for src.services.schema — schema migration listing per project."""
import pytest

from src.services import schema as schema_service


def _isolated_registry(monkeypatch, tmp_path):
    """Redirect GlobalRegistryStore to a fresh tmp dir."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    return cfg


def test_get_schema_unknown_project_raises_not_found(monkeypatch, tmp_path):
    """Unknown project_id raises ProjectNotFoundError so the route maps to 404.

    Audit I7: the previous behaviour returned 200 with an empty list, which
    conflated unknown-project with known-project-no-pending-migrations.
    """
    from src.project.context import ProjectNotFoundError

    _isolated_registry(monkeypatch, tmp_path)

    with pytest.raises(ProjectNotFoundError):
        schema_service.get_schema("does-not-exist")


def test_get_schema_filters_by_project_version(monkeypatch, tmp_path):
    """Only migrations at or below the project's version are returned."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    from src.schemas.registry import MigrationRegistry
    from src.schemas.migration import SchemaVersion

    _isolated_registry(monkeypatch, tmp_path)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(tmp_path / "p"),
        last_opened=1000, schema_version="v1.0",
    ))

    # Reset migration registry to a known state
    MigrationRegistry._clear()
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, _dummy_mig()
    )
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, _dummy_mig()
    )

    result = schema_service.get_schema("u")
    assert result["schema_version"] == "v1.0"
    # Only the v1.0 -> v2.0 edge is reachable from v1.0
    assert len(result["schemas"]) == 1
    edge = result["schemas"][0]
    assert edge["from"] == "v1.0"
    assert edge["to"] == "v2.0"


def test_get_schema_at_higher_version_includes_all(monkeypatch, tmp_path):
    """A project at v2.1 sees all edges up to and including v2.1."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    from src.schemas.registry import MigrationRegistry
    from src.schemas.migration import SchemaVersion

    _isolated_registry(monkeypatch, tmp_path)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(tmp_path / "p"),
        last_opened=1000, schema_version="v2.1",
    ))

    MigrationRegistry._clear()
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, _dummy_mig()
    )
    MigrationRegistry.register(
        "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, _dummy_mig()
    )

    result = schema_service.get_schema("u")
    assert len(result["schemas"]) == 2


def test_get_schema_invalid_version_returns_empty(monkeypatch, tmp_path):
    """If project has a bogus version string, behave like unknown project."""
    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry

    _isolated_registry(monkeypatch, tmp_path)
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(tmp_path / "p"),
        last_opened=1000, schema_version="not-a-version",
    ))

    result = schema_service.get_schema("u")
    assert result["schema_version"] is None
    assert result["schemas"] == []


def _dummy_mig():
    """A no-op migration for testing the registry."""
    from src.schemas.migration import Migration, MigrationPlan, MigrationResult
    class _M(Migration):
        schema_name = "wiki_page"
        from_version = None
        to_version = None
        def preview(self, ctx): return MigrationPlan(None, None, ["dummy"], [], True)
        def up(self, ctx): return MigrationResult(success=True)
        def down(self, ctx): return MigrationResult(success=True)
    return _M()
