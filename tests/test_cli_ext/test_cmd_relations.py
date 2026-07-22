"""Tests for src/cli_ext/relations_cmd.py"""
import argparse
from pathlib import Path

from src.wiki.types import PageType, WikiPage
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page
from src.wiki.relations import Relation, RelationSync
from src.project.context import ProjectContext
from src.project import paths as project_paths
from src.project import registry as project_registry


def _make_real_ctx(monkeypatch, tmp_path: Path, name: str = "p") -> ProjectContext:
    """Bootstrap a real ProjectContext at tmp_path with a hermetic global config dir.

    Without this, ProjectContext.from_path writes to the user's real global
    config dir (polluting test runs).
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(project_paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(project_registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")
    return ProjectContext.from_path(tmp_path, name=name)


def _make_args(**kw):
    """Build an argparse.Namespace with defaults."""
    defaults = dict(project="proj-test", page_id="a", from_id="a", to_id="b", depth=1, name="myrel")
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_cmd_relations_list(monkeypatch, tmp_path, capsys):
    """relations list prints outgoing relations."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="b", title="B", type=PageType.ENTITY, body=""))
    RelationSync.sync_page(p, "a", [Relation(target_id="b", type="references", weight=0.7)])

    real_ctx = _make_real_ctx(monkeypatch, tmp_path, name="p")
    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: real_ctx)

    relations_cmd.cmd_relations_list(_make_args(page_id="a"))
    captured = capsys.readouterr()
    assert "b" in captured.out
    assert "references" in captured.out


def test_cmd_relations_list_with_real_context(monkeypatch, tmp_path, capsys):
    """Integration: real ProjectContext (.path, not .paths) flows into handlers.

    Exercises the public ProjectContext.from_path() bootstrap path end-to-end
    (project.json + global registry) with a hermetic config dir, then runs the
    list command through the real handler. This guards Finding 1: handlers must
    use WikiPaths(ctx.path), not the nonexistent ctx.paths.
    """
    from src.wiki.types import PageType, WikiPage
    from src.wiki.ensure import ensure_knowledge_base
    from src.wiki.page_writer import write_page
    from src.wiki.relations import Relation, RelationSync
    from src.project.context import ProjectContext

    ensure_knowledge_base(tmp_path)
    p_wiki = WikiPaths(tmp_path)
    write_page(p_wiki, WikiPage(id="a", title="A", type=PageType.ENTITY, body=""))
    write_page(p_wiki, WikiPage(id="b", title="B", type=PageType.ENTITY, body=""))
    RelationSync.sync_page(p_wiki, "a", [Relation(target_id="b", type="references")])

    real_ctx = ProjectContext.from_path(tmp_path, name="p") if False else _make_real_ctx(
        monkeypatch, tmp_path, name="p"
    )

    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: real_ctx)

    args = argparse.Namespace(project="any", page_id="a", from_id="a", to_id="b", depth=1, name="myrel")
    relations_cmd.cmd_relations_list(args)
    captured = capsys.readouterr()
    assert "b" in captured.out
    assert "references" in captured.out


def test_cmd_relations_backlinks(monkeypatch, tmp_path, capsys):
    """relations backlinks prints pages that link to this one."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="b", title="B", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="c", title="C", type=PageType.ENTITY, body=""))
    RelationSync.sync_page(p, "a", [Relation(target_id="c", type="references")])
    RelationSync.sync_page(p, "b", [Relation(target_id="c", type="supports")])

    real_ctx = _make_real_ctx(monkeypatch, tmp_path, name="p")
    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: real_ctx)

    relations_cmd.cmd_relations_backlinks(_make_args(page_id="c"))
    captured = capsys.readouterr()
    assert "a" in captured.out
    assert "b" in captured.out


def test_cmd_relations_path(monkeypatch, tmp_path, capsys):
    """relations path prints the edges of the shortest path."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="a", title="A", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="b", title="B", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="c", title="C", type=PageType.ENTITY, body=""))
    RelationSync.sync_page(p, "a", [Relation(target_id="b", type="references")])
    RelationSync.sync_page(p, "b", [Relation(target_id="c", type="references")])

    real_ctx = _make_real_ctx(monkeypatch, tmp_path, name="p")
    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: real_ctx)

    relations_cmd.cmd_relations_path(_make_args(from_id="a", to_id="c"))
    captured = capsys.readouterr()
    assert "a" in captured.out and "b" in captured.out
    assert "b" in captured.out and "c" in captured.out
