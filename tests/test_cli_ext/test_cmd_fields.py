"""Tests for src/cli_ext/fields_cmd.py."""
import argparse
import pytest
from src.wiki.types import PageType, WikiPage
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page
from src.project.context import ProjectContext
from src.project import paths as project_paths
from src.project import registry as project_registry


def _make_args(project="proj-test", path="x.md", page_path="x.md", all_=False):
    return argparse.Namespace(
        project=project, path=path, page_path=page_path, all=all_,
    )


def _make_real_ctx(monkeypatch, tmp_path, name: str = "p") -> ProjectContext:
    """Bootstrap a real ProjectContext at tmp_path with a hermetic global config dir."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(project_paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(project_registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")
    return ProjectContext.from_path(tmp_path, name=name)


def _bootstrap_project(tmp_path):
    """Create a real ProjectContext at tmp_path."""
    ensure_knowledge_base(tmp_path)
    return None  # ProjectContext is created by _make_real_ctx


def test_fields_validate_ok(tmp_path, monkeypatch, capsys):
    """Valid page passes fields validate."""
    _bootstrap_project(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(
        id="valid", title="Valid", type=PageType.ENTITY,
        sources=["raw/sources/x.pdf"], body="x",
    ))
    # Inject real ctx via _resolve_ctx stub
    ctx = _make_real_ctx(monkeypatch, tmp_path)
    import src.cli_ext.fields_cmd as fc
    monkeypatch.setattr(fc, "_resolve_ctx", lambda proj: (ctx, paths))

    fc.cmd_fields_validate(_make_args(path="wiki/entities/valid.md"))
    out = capsys.readouterr().out
    assert "OK" in out


def test_fields_validate_missing_id(tmp_path, monkeypatch, capsys):
    """Page with missing sources fails fields validate."""
    _bootstrap_project(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(
        id="bad", title="Bad", type=PageType.ENTITY,
        sources=[], body="x",  # missing sources triggers L0 error
    ))
    ctx = _make_real_ctx(monkeypatch, tmp_path)
    import src.cli_ext.fields_cmd as fc
    monkeypatch.setattr(fc, "_resolve_ctx", lambda proj: (ctx, paths))

    with pytest.raises(SystemExit) as exc_info:
        fc.cmd_fields_validate(_make_args(path="wiki/entities/bad.md"))
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "sources" in out


def test_tags_validate_invalid(tmp_path, monkeypatch, capsys):
    """Page with non-namespace tags fails tags validate."""
    _bootstrap_project(tmp_path)
    paths = WikiPaths(tmp_path)
    # Write a page with frontmatter that has invalid tags
    page_path = paths.wiki_entities / "tagged.md"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(
        "---\n"
        "id: tagged\n"
        "title: T\n"
        "type: entity\n"
        "tags:\n"
        "  - genre/noir\n"
        "  - bad-tag-no-prefix\n"
        "  - foo/bar\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    ctx = _make_real_ctx(monkeypatch, tmp_path)
    import src.cli_ext.fields_cmd as fc
    monkeypatch.setattr(fc, "_resolve_ctx", lambda proj: (ctx, paths))

    with pytest.raises(SystemExit) as exc_info:
        fc.cmd_tags_validate(_make_args(page_path="wiki/entities/tagged.md"))
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "bad-tag-no-prefix" in out or "foo/bar" in out
