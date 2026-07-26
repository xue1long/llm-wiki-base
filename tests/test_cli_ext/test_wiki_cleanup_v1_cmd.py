"""Tests for wiki-cleanup-v1-data CLI (Plan v2.5, strict-scope cleanup).

Three handler-level tests + one CLI registration smoke test. Each
destructive path is exercised through ``_atomic_snapshot`` or the
``cmd_*`` handler directly so failure injection is straightforward.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli_ext import wiki_cleanup_v1_cmd as cleanup


REPO = Path(__file__).parent.parent.parent


def _run_cli(*args, cwd=None, env=None) -> subprocess.CompletedProcess:
    base_env = {**os.environ, "PYTHONPATH": str(REPO),
                "HTTP_PROXY": "", "HTTPS_PROXY": "",
                "http_proxy": "", "https_proxy": ""}
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "src.cli", "wiki-cleanup-v1-data", *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        env=base_env,
    )


def _seed_wiki(wiki_root: Path, n_entity: int = 2, n_source: int = 1) -> None:
    """Populate ``wiki_root`` with ``n_entity`` entity + ``n_source`` source pages.

    Uses the real ``WikiPaths`` so ``write_page`` works (it reads
    many typed attributes from the paths object).
    """
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(wiki_root.parent)

    for i in range(n_entity):
        write_page(paths, WikiPage(
            id=f"entity-{i:02d}", title=f"Entity {i:02d}",
            type=PageType.ENTITY, body=f"entity {i:02d} body",
        ))
    for i in range(n_source):
        write_page(paths, WikiPage(
            id=f"kb-test-{i:02d}", title=f"Source {i:02d}.md",
            type=PageType.SOURCE, body=f"source {i:02d} body",
            sources=[f"raw/sources/source-{i:02d}.md"],
        ))


class _PathsStub:
    """Read-only WikiPaths-compatible stub for --delete safety checks.

    The cleanup module reads only ``root``, ``wiki``, ``raw_sources``
    from the paths object during deletion. We construct a thin
    stub here so the safety-rail branch can be tested without
    registering a real project.
    """
    def __init__(self, root: Path):
        self.root = root
        self.wiki = root / "wiki"
        self.raw_sources = root / "raw" / "sources"


# ---------------------------------------------------------------------------
# 1) Snapshot rollback on partial failure
# ---------------------------------------------------------------------------


def test_archive_state_atomic_on_partial_failure(tmp_path, monkeypatch):
    """Inject OSError on the 2nd shutil.move — assert first file is rolled back."""
    root = tmp_path / "p"
    root.mkdir()
    wiki = root / "wiki"
    (root / "raw" / "sources").mkdir(parents=True)
    _seed_wiki(wiki, n_entity=2, n_source=1)

    real_move = shutil.move
    n = [0]

    def flaky_move(src, dst):
        n[0] += 1
        if n[0] == 2:
            raise OSError("simulated mid-snapshot failure")
        return real_move(src, dst)

    monkeypatch.setattr(cleanup.shutil, "move", flaky_move)

    dst = wiki / "_archive" / "snap1"
    with pytest.raises(SystemExit) as exc:
        cleanup._atomic_snapshot(wiki, dst)
    assert exc.value.code == 3

    # First file (one of the .md files in alphabetical order) must
    # have been rolled back to its original location.
    # Order from _list_wiki_files:
    # entities/entity-00.md, entities/entity-01.md, sources/kb-test-00.md,
    # index.md, log.md (last 2 created by ensure_knowledge_base)
    assert (wiki / "entities" / "entity-00.md").exists(), \
        "first moved file should have rolled back to original location"
    # Second file should still be at original location (we never moved it).
    assert (wiki / "entities" / "entity-01.md").exists()


# ---------------------------------------------------------------------------
# 2) Dry-run never mutates
# ---------------------------------------------------------------------------


def test_rebuild_dry_run_does_not_touch_files(tmp_path, monkeypatch):
    """Default rebuild (no --apply) must not call _rebuild_state."""
    root = tmp_path / "p"
    root.mkdir()
    wiki = root / "wiki"
    (root / "raw" / "sources").mkdir(parents=True)
    _seed_wiki(wiki, n_entity=2, n_source=1)

    # If this fires, the dry-run path took a destructive branch.
    rebuild_calls = {"n": 0}
    def trap_rebuild(*a, **kw):
        rebuild_calls["n"] += 1
        return [], {}

    monkeypatch.setattr(cleanup, "_rebuild_state", trap_rebuild)
    # Stub _resolve so we don't need a real registered project.
    monkeypatch.setattr(cleanup, "_resolve", lambda arg: (None, _PathsStub(root)))

    args = argparse.Namespace(project="p", apply=False, delete=None, candidates=False)
    rc = cleanup.cmd_wiki_rebuild_from_raws(args)
    assert rc == 0
    assert rebuild_calls["n"] == 0, "dry-run must not call _rebuild_state"

    # Wiki content unchanged.
    assert (wiki / "entities" / "entity-00.md").exists()
    assert (wiki / "sources" / "kb-test-00.md").exists()


# ---------------------------------------------------------------------------
# 3) --delete safety rails (raw/, outside wiki/)
# ---------------------------------------------------------------------------


def test_delete_refuses_raws(tmp_path, monkeypatch):
    """Deleting a raw/ file must be refused with exit code 6."""
    root = tmp_path / "p"
    root.mkdir()
    wiki = root / "wiki"
    raw = root / "raw" / "sources"
    raw.mkdir(parents=True)
    _seed_wiki(wiki, n_entity=1, n_source=1)
    target_raw = raw / "kb-test-00.md"
    target_raw.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(cleanup, "_resolve", lambda arg: (None, _PathsStub(root)))

    args = argparse.Namespace(
        project="p", apply=False, delete=str(target_raw), candidates=False,
    )
    rc = cleanup.cmd_wiki_rebuild_from_raws(args)
    assert rc == 6, f"expected 6 (raw refusal), got {rc}"
    assert target_raw.exists(), "raw/ file must not have been deleted"


def test_delete_refuses_outside_wiki_root(tmp_path, monkeypatch):
    """A path outside wiki/ tree must be refused with exit code 5."""
    root = tmp_path / "p"
    root.mkdir()
    wiki = root / "wiki"
    _seed_wiki(wiki, n_entity=1, n_source=1)
    outside = root / "somewhere-else.md"
    outside.write_text("data", encoding="utf-8")

    monkeypatch.setattr(cleanup, "_resolve", lambda arg: (None, _PathsStub(root)))

    args = argparse.Namespace(
        project="p", apply=False, delete=str(outside), candidates=False,
    )
    rc = cleanup.cmd_wiki_rebuild_from_raws(args)
    assert rc == 5, f"expected 5 (outside-wiki refusal), got {rc}"
    assert outside.exists()


def test_delete_refuses_missing_file(tmp_path, monkeypatch):
    """Deleting a path that no longer exists must error 7."""
    root = tmp_path / "p"
    root.mkdir()
    wiki = root / "wiki"
    _seed_wiki(wiki, n_entity=1, n_source=1)
    bogus = wiki / "sources" / "does-not-exist.md"

    monkeypatch.setattr(cleanup, "_resolve", lambda arg: (None, _PathsStub(root)))

    args = argparse.Namespace(
        project="p", apply=False, delete=str(bogus), candidates=False,
    )
    rc = cleanup.cmd_wiki_rebuild_from_raws(args)
    assert rc == 7, f"expected 7 (missing file), got {rc}"


# ---------------------------------------------------------------------------
# 4) CLI registration smoke
# ---------------------------------------------------------------------------


def test_cli_registered_help():
    r = _run_cli("--help")
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "archive-state" in r.stdout
    assert "rebuild-from-raws" in r.stdout
    assert "restore-from-archive" in r.stdout
