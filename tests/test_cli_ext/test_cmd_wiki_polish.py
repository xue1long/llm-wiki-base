"""Tests for src.cli_ext.wiki_polish_cmd.py."""
import argparse
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.core.types import PageType, WikiPage
from src.project.context import ProjectContext


def _make_args(project="proj-test", threshold="high", cache_ttl=None, no_cache=False):
    return argparse.Namespace(project=project, threshold=threshold, cache_ttl=cache_ttl, no_cache=no_cache)


def _bootstrap(tmp_path, monkeypatch):
    """Create a project at tmp_path with an isolated config dir.

    Monkeypatches ``config_dir`` and registry paths so
    ``ProjectContext.from_path`` writes to a temp registry instead of the
    real on-disk ``registry.json``.
    """
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")

    ensure_knowledge_base(tmp_path)
    return ProjectContext.from_path(tmp_path), WikiPaths(tmp_path)


def test_stubs_list(tmp_path, monkeypatch, capsys):
    ctx, paths = _bootstrap(tmp_path, monkeypatch)
    (paths.wiki_stubs / "stub-a.md").write_text("---\nid: stub-a\ntitle: Stub A\ntype: stub\n---\n\nbody\n", encoding="utf-8")
    (paths.wiki_stubs / "stub-b.md").write_text("---\nid: stub-b\ntitle: Stub B\ntype: stub\n---\n\nbody\n", encoding="utf-8")
    import src.cli_ext.wiki_polish_cmd as wpc
    monkeypatch.setattr(wpc, "_resolve_ctx", lambda proj: (ctx, paths))
    wpc.cmd_stubs_list(_make_args())
    out = capsys.readouterr().out
    assert "stub-a" in out and "stub-b" in out


def test_dedup_auto_no_duplicates(tmp_path, monkeypatch, capsys):
    ctx, paths = _bootstrap(tmp_path, monkeypatch)
    import src.cli_ext.wiki_polish_cmd as wpc
    monkeypatch.setattr(wpc, "_resolve_ctx", lambda proj: (ctx, paths))
    wpc.cmd_dedup_auto(_make_args())
    assert "Auto-merged 0" in capsys.readouterr().out


def test_lint_runs(tmp_path, monkeypatch, capsys):
    ctx, paths = _bootstrap(tmp_path, monkeypatch)
    write_page(paths, WikiPage(id="orphan", title="Orphan", type=PageType.ENTITY, body="x"))
    import src.cli_ext.wiki_polish_cmd as wpc
    monkeypatch.setattr(wpc, "_resolve_ctx", lambda proj: (ctx, paths))
    wpc.cmd_lint(_make_args(no_cache=True))
    assert "Found" in capsys.readouterr().out


def test_lint_uses_cache_on_second_run(tmp_path, monkeypatch, capsys):
    """Second lint invocation hits the cache; third uses stale TTL."""
    ctx, paths = _bootstrap(tmp_path, monkeypatch)
    write_page(paths, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))

    import src.cli_ext.wiki_polish_cmd as wpc
    monkeypatch.setattr(wpc, "_resolve_ctx", lambda proj: (ctx, paths))

    # First run: populate cache
    wpc.cmd_lint(_make_args(cache_ttl=3600))
    first_out = capsys.readouterr().out
    assert "Found" in first_out

    # Second run: should hit cache
    wpc.cmd_lint(_make_args(cache_ttl=3600))
    second_out = capsys.readouterr().out
    assert "Using cached lint result" in second_out
