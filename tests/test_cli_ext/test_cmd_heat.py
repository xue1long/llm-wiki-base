"""Tests for src/cli_ext/heat_cmd.py."""
import argparse
import time
from pathlib import Path

from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
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


def _make_args(project="proj-test", page_id="a", limit=10, dry_run=False):
    return argparse.Namespace(
        project=project, page_id=page_id, limit=limit, dry_run=dry_run,
    )


def _bootstrap(tmp_path):
    ensure_knowledge_base(tmp_path)
    return ProjectContext.from_path(tmp_path), WikiPaths(tmp_path)


def test_heat_show(tmp_path, monkeypatch, capsys):
    """heat show prints page heat + last_used_at + zombie_since."""
    ctx, paths = _bootstrap(tmp_path)
    write_page(paths, WikiPage(id="hot", title="Hot", type=PageType.ENTITY, body="", heat=80, last_used_at=12345))

    import src.cli_ext.heat_cmd as hc
    monkeypatch.setattr(hc, "_resolve_ctx", lambda proj: (ctx, paths))

    hc.cmd_heat_show(_make_args(page_id="hot"))
    out = capsys.readouterr().out
    assert "heat: 80" in out
    assert "last_used_at: 12345" in out


def test_decay(tmp_path, monkeypatch, capsys):
    """heat decay applies decay events to old pages."""
    ctx, paths = _bootstrap(tmp_path)
    old_ts = int(time.time() * 1000) - 31 * 86400 * 1000
    write_page(paths, WikiPage(id="old", title="Old", type=PageType.ENTITY, body="", heat=80, last_used_at=old_ts))

    import src.cli_ext.heat_cmd as hc
    monkeypatch.setattr(hc, "_resolve_ctx", lambda proj: (ctx, paths))

    hc.cmd_heat_decay(_make_args())
    out = capsys.readouterr().out
    assert "Applied 1 decay events" in out


def test_zombies_list(tmp_path, monkeypatch, capsys):
    """heat zombies lists pages with zombie_since set."""
    ctx, paths = _bootstrap(tmp_path)
    write_page(paths, WikiPage(id="z", title="Zombie", type=PageType.ENTITY, body="", zombie_since=12345))
    write_page(paths, WikiPage(id="alive", title="Alive", type=PageType.ENTITY, body="", zombie_since=None))

    import src.cli_ext.heat_cmd as hc
    monkeypatch.setattr(hc, "_resolve_ctx", lambda proj: (ctx, paths))

    hc.cmd_heat_zombies(_make_args())
    out = capsys.readouterr().out
    assert "z" in out
    assert "alive" not in out
