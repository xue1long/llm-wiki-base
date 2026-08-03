"""Tests for src.lib.project — centralised project resolution helpers.

Replaces the 9 hand-rolled `_resolve_ctx` copies that previously lived
across cli_ext/* and server/routes/* (each duplicated the same
try/except + WikiPaths construction logic).
"""
import pytest

from src.project.context import ProjectContext
from src.wiki.core.paths import WikiPaths


def test_resolve_project_returns_ctx_and_paths(monkeypatch, tmp_path):
    """resolve_project must return a (ctx, paths) tuple ready for use."""
    from src.lib import project as lib_project

    # Set up a real project at tmp_path
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "test-uuid", "name": "test", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    # Stub GlobalRegistryStore so resolve() can find this project
    from src.project.registry import ProjectRegistryEntry, GlobalRegistryStore
    fake_entry = ProjectRegistryEntry(
        id="test-uuid", name="test", path=str(project_dir),
        last_opened=1000, schema_version="v2.0",
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_id", staticmethod(lambda _id: fake_entry if _id == "test-uuid" else None)
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_name", staticmethod(lambda name: fake_entry if name == "test" else None)
    )

    # Stub from_path to avoid writing to global registry
    monkeypatch.setattr(
        ProjectContext, "from_path", classmethod(lambda cls, p, name=None: ProjectContext(
            identity=type("I", (), {"id": "test-uuid"})(),
            path=p, name=name or "test", schema_version="v2.0",
        ))
    )

    ctx, paths = lib_project.resolve_project("test-uuid", by_id_only=True)
    assert isinstance(ctx, ProjectContext)
    assert isinstance(paths, WikiPaths)
    assert paths.root == project_dir


def test_resolve_project_propagates_error(monkeypatch):
    """If the project is not found, the underlying ProjectNotFoundError is raised
    (caller decides how to handle — sys.exit for CLI, HTTPException for routes)."""
    from src.lib import project as lib_project
    from src.project import context as ctx_module
    from src.project.registry import GlobalRegistryStore

    monkeypatch.setattr(
        GlobalRegistryStore, "by_id", staticmethod(lambda _id: None)
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_name", staticmethod(lambda name: None)
    )

    with pytest.raises(ctx_module.ProjectNotFoundError):
        lib_project.resolve_project("nonexistent", by_id_only=True)


def test_resolve_ctx_only_returns_ctx(monkeypatch, tmp_path):
    """resolve_ctx_only returns just the ProjectContext (no WikiPaths)."""
    from src.lib import project as lib_project
    from src.project.registry import ProjectRegistryEntry, GlobalRegistryStore

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    (project_dir / ".llm-wiki").mkdir()
    (project_dir / ".llm-wiki" / "project.json").write_text(
        '{"id": "ctx-uuid", "name": "ctx", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )
    fake_entry = ProjectRegistryEntry(
        id="ctx-uuid", name="ctx", path=str(project_dir),
        last_opened=1000, schema_version="v2.0",
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_id", staticmethod(lambda _id: fake_entry if _id == "ctx-uuid" else None)
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_name", staticmethod(lambda name: fake_entry if name == "ctx" else None)
    )
    monkeypatch.setattr(
        ProjectContext, "from_path", classmethod(lambda cls, p, name=None: ProjectContext(
            identity=type("I", (), {"id": "ctx-uuid"})(),
            path=p, name=name or "ctx", schema_version="v2.0",
        ))
    )

    ctx = lib_project.resolve_ctx_only("ctx-uuid", by_id_only=True)
    assert isinstance(ctx, ProjectContext)
    assert ctx.id == "ctx-uuid"
