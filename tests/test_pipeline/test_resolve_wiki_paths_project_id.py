"""Audit I5 regression: pipeline resolves WikiPaths from the originating
project_id (so multi-project ingest writes to the right project).

Previously, ``_resolve_wiki_paths()`` returned ``Path.cwd() / "Knowledge"``
unconditionally — multi-project ingest wrote to the wrong project.
After the fix, when ``project_id`` is passed, the project is looked up
in the global registry and ``WikiPaths(root)`` is built from it.
"""
import pytest

from src.pipeline import pipeline as pipeline_mod


def test_resolve_wiki_paths_uses_project_id_when_provided(tmp_path, monkeypatch):
    """When project_id is given, resolve WikiPaths from the registry entry."""
    project_root = tmp_path / "myproject"
    project_root.mkdir()
    monkeypatch.setattr(pipeline_mod.Path, "cwd", lambda: tmp_path)

    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    # Isolated registry directory
    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)

    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="abc-123", name="myproject", path=str(project_root),
        last_opened=1000, schema_version="v2.0",
    ))

    paths = pipeline_mod._resolve_wiki_paths(project_id="abc-123")
    assert paths.root == project_root


def test_resolve_wiki_paths_falls_back_to_cwd_when_no_id(tmp_path, monkeypatch):
    """Legacy callers without project_id resolve to CWD as the wiki root."""
    monkeypatch.chdir(tmp_path)
    paths = pipeline_mod._resolve_wiki_paths()
    assert paths.root == tmp_path


def test_resolve_wiki_paths_raises_for_unknown_project_id(tmp_path, monkeypatch):
    """Unknown project_id now raises ValueError instead of silently falling
    back to CWD — silent fallback wrote wiki pages to the wrong directory."""
    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="not found in the global registry"):
        pipeline_mod._resolve_wiki_paths(project_id="does-not-exist")