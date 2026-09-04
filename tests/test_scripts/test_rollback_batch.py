"""Phase 4.6 tests — scripts/rollback_batch.py 回滚脚本（git checkout + 向量重建）。

计划 guidance #6（P1 P0 加固）：回滚 = git checkout + 向量重建双动作脚本化。
- 回滚到批前 git 快照（batch_build_state.json 里记录的 git_snapshot HEAD）
- 向量重建：rebuild_vector_schema（显式 drop + 重建）——维度迁移决策已由
  T4.3 完成，回滚不静默 drop
- 未记录快照/非 git 仓库 → 明确报错，不做部分回滚
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.wiki.storage.ensure import ensure_knowledge_base  # noqa: E402
from src.services.batch_state import save_batch_state  # noqa: E402


@pytest.fixture
def git_wiki(tmp_path: Path) -> Path:
    """A git repo wiki with a committed base and an uncommitted change."""
    ensure_knowledge_base(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"],
                   check=True)
    # base commit: one raw + one source page
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "a.md").write_text("# 素材A\n\n内容", encoding="utf-8")
    src = tmp_path / "wiki" / "sources"
    src.mkdir(parents=True, exist_ok=True)
    (src / "src-a.md").write_text(
        "---\nid: src-a\ntitle: 源A\ntype: source\nsources:\n- raw/sources/a.md\n"
        "---\n\n旧正文\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"],
                   check=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    # 记录批前快照（模拟 executor 每批前写的 git_snapshot）——必须包 WikiPaths！
    from src.wiki.core.paths import WikiPaths
    save_batch_state(WikiPaths(tmp_path), {
        "batch_0": {"status": "committed", "git_snapshot": head},
    })
    # 批后改动（未提交）：新概念页 + 修改源页
    (tmp_path / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "concepts" / "c1.md").write_text(
        "---\nid: c1\ntitle: 概念\ntype: concept\nsources:\n- raw/sources/a.md\n"
        "---\n\n新概念\n", encoding="utf-8")
    (src / "src-a.md").write_text(
        "---\nid: src-a\ntitle: 源A\ntype: source\nsources:\n- raw/sources/a.md\n"
        "---\n\n批后正文\n", encoding="utf-8")
    return tmp_path


def _run_rollback(root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "rollback_batch.py"),
           str(root), "--yes"]
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=120, cwd=str(REPO_ROOT))


def test_rollback_restores_snapshot_and_rebuilds_vectors(git_wiki: Path) -> None:
    r = _run_rollback(git_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    # 未提交的新概念页被 git checkout 清除
    assert not (git_wiki / "wiki" / "concepts" / "c1.md").exists()
    # 源页回到 base 内容
    text = (git_wiki / "wiki" / "sources" / "src-a.md").read_text(encoding="utf-8")
    assert "旧正文" in text and "批后正文" not in text
    # 向量已重建（lancedb 表存在）
    from src.wiki.core.paths import WikiPaths
    from src.vector.store import get_table, init_vector_store_for_paths
    paths = WikiPaths(git_wiki)
    init_vector_store_for_paths(paths)
    assert get_table(paths) is not None


def test_rollback_without_snapshot_errors(git_wiki: Path) -> None:
    from src.wiki.core.paths import WikiPaths
    save_batch_state(WikiPaths(git_wiki), {"batch_0": {"status": "committed"}})  # 无快照
    r = _run_rollback(git_wiki)
    assert r.returncode == 1
    assert "snapshot" in r.stderr.lower() or "snapshot" in r.stdout.lower()
    # 批后改动未被部分回滚（明确报错，不做半吊子回滚）
    assert (git_wiki / "wiki" / "concepts" / "c1.md").exists()


def test_rollback_non_git_errors(tmp_path: Path) -> None:
    ensure_knowledge_base(tmp_path)
    r = _run_rollback(tmp_path)
    assert r.returncode == 1
    assert "git" in (r.stderr + r.stdout).lower()
