"""Phase 0.3 tests — rebuild_index.py catalog regeneration."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)

    def page(rel: str, content: str) -> None:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    page("wiki/sources/s-a.md",
         "---\nid: s-a\ntitle: 源A\ntype: source\n---\n\n## 摘要\n\nx\n")
    page("wiki/concepts/c1.md",
         "---\nid: c1\ntitle: 概念一\ntype: concept\n---\n\n## 定义\n\n[[s-a]]\n")
    # stale index with a wrong entry
    page("wiki/index.md", "# Wiki Index\n\n- **stale** (entity) — 旧\n")
    return tmp_path


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "rebuild_index.py"),
         str(root), *extra],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )


def test_rebuild_index(mini_wiki: Path) -> None:
    r = _run(mini_wiki)
    assert r.returncode == 0, r.stderr
    index = (mini_wiki / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "- **s-a** (source) — 源A" in index
    assert "- **c1** (concept) — 概念一" in index
    assert "stale" not in index
    # ordered source before concept
    assert index.index("s-a") < index.index("c1")


def test_rebuild_index_dry_run(mini_wiki: Path) -> None:
    before = (mini_wiki / "wiki" / "index.md").read_text(encoding="utf-8")
    r = _run(mini_wiki, "--dry-run")
    assert r.returncode == 0, r.stderr
    after = (mini_wiki / "wiki" / "index.md").read_text(encoding="utf-8")
    assert before == after
    assert "would write 2 entries" in r.stdout
