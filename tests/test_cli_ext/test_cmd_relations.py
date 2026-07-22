"""Tests for src/cli_ext/relations_cmd.py"""
import argparse

from src.wiki.types import PageType, WikiPage
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page
from src.wiki.relations import Relation, RelationSync


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

    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: type("Ctx", (), {"paths": p})())

    relations_cmd.cmd_relations_list(_make_args(page_id="a"))
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

    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: type("Ctx", (), {"paths": p})())

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

    from src.cli_ext import relations_cmd
    monkeypatch.setattr(relations_cmd, "_resolve", lambda pid: type("Ctx", (), {"paths": p})())

    relations_cmd.cmd_relations_path(_make_args(from_id="a", to_id="c"))
    captured = capsys.readouterr()
    assert "a" in captured.out and "b" in captured.out
    assert "b" in captured.out and "c" in captured.out