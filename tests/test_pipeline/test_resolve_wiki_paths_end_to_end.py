"""End-to-end: project init + _resolve_wiki_paths covers both branches.

Audit F3 changed the fallback to WikiPaths(Path.cwd()) so single-project
CLI mode writes to the canonical <root>/wiki/ shape. This test exercises
both branches of _resolve_wiki_paths via the full project-init flow so
the CWD-fallback and the registered-project branches stay coherent.
"""
import pytest
from src.project.context import ProjectContext
from src.wiki.core.paths import WikiPaths
from src.cli_ext import project_cmd
from src.pipeline.pipeline import _resolve_wiki_paths


def test_resolve_with_registered_project(tmp_path, monkeypatch):
    """When project_id matches a registered entry, return its WikiPaths."""
    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)

    project_root = tmp_path / "myproject"
    project_root.mkdir()
    (project_root / ".llm-wiki").mkdir()
    (project_root / ".llm-wiki" / "project.json").write_text(
        '''{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}''',
        encoding="utf-8",
    )

    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(project_root),
        last_opened=1000, schema_version="v2.0",
    ))

    paths = _resolve_wiki_paths(project_id="u")
    assert paths.root == project_root


def test_resolve_fallback_returns_cwd(tmp_path, monkeypatch):
    """When project_id is None and no fallback registry matches, the
    resolved WikiPaths uses CWD as the project root (the canonical
    wiki-v2 shape, not the legacy <cwd>/Knowledge/ double-nest)."""
    monkeypatch.chdir(tmp_path)
    paths = _resolve_wiki_paths()
    assert paths.root == tmp_path


def test_resolve_raises_for_unknown_id(tmp_path, monkeypatch):
    """Unknown project_id raises ValueError — silent fallback wrote wiki pages
    to the wrong directory with no error."""
    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="not found in the global registry"):
        _resolve_wiki_paths(project_id="does-not-exist")
