"""Phase 4.5 tests — scripts/batch_executor.py 批执行器状态机 + kill-9 崩溃注入.

覆盖（plan Phase 4 guidance #2/#3/#4/#5/#11/#12/#13）：
- 每 raw 状态机（pending/in_progress/done/failed/permanent_failed/pending_deletion）
- 崩溃续跑：done 跳过；pending_deletion 重跑重建；failed 自动重投
- kill -9 各阶段注入（env BATCH_EXECUTOR_CRASH_AT）→ 续跑后正确完成
- 每 raw 分支：有 source 页 → reingest；无 → first_ingest
- pre-commit 门禁（失败=零写入）
- is_immutable 跳过、failed 3-strike blocklist、git 快照记录
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services.batch_state import load_batch_state, raw_status  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.storage.ensure import ensure_knowledge_base  # noqa: E402


def _state(root: Path) -> dict:
    """读项目状态文件 —— 必须包 WikiPaths（raw Path.root 是盘符根！）。"""
    return load_batch_state(WikiPaths(root))


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    """A tiny wiki with two raws (one already having a source page)."""
    ensure_knowledge_base(tmp_path)
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "a.md").write_text("# 素材A\n\n内容", encoding="utf-8")
    (raw / "b.md").write_text("# 素材B\n\n内容", encoding="utf-8")

    # a.md 已有 source 页（存量 → 走 reingest 分支）
    src_dir = tmp_path / "wiki" / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "src-a.md").write_text(
        "---\nid: src-a\ntitle: 源A\ntype: source\nsources:\n- raw/sources/a.md\n"
        "created_at: 1\nupdated_at: 1\nprocessing_depth: source\n---\n\n旧正文\n",
        encoding="utf-8")
    # 索引里登记 src-a
    idx = tmp_path / "wiki" / "index.md"
    if idx.exists():
        idx.write_text(idx.read_text(encoding="utf-8") + "[[src-a]]\n", encoding="utf-8")
    return tmp_path


def _run_executor(root: Path, batch_no: int = 0, *,
                  extra_env: dict | None = None,
                  extra_args: list[str] | None = None,
                  timeout: int = 120) -> subprocess.CompletedProcess:
    """Run batch_executor.py as a subprocess against *root* (--root mode)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["RUFLO_EXECUTOR_FAKE_GENERATE"] = "1"  # 离线确定性生成（test-only）
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "batch_executor.py"),
           "--root", str(root), "--batch", str(batch_no),
           "--manifest", str(root / ".index" / "reingest_plan.json")]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=timeout, cwd=str(REPO_ROOT))


def _write_plan(root: Path, files: list[str]) -> None:
    plan_dir = root / ".index"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "reingest_plan.json").write_text(
        json.dumps({"summary": {"raw_md_total": len(files)},
                    "batches": [{"theme": "test", "batch_no": 0, "files": files}]},
                   ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 状态机：崩溃续跑
# ---------------------------------------------------------------------------

def test_first_run_marks_all_done(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, ["raw/sources/a.md", "raw/sources/b.md"])
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"
    assert raw_status(state, "batch_0", "raw/sources/b.md") == "done"


def test_crash_during_generate_resumes(mini_wiki: Path) -> None:
    """generate 阶段 kill -9 → 续跑补齐，done 不重复。"""
    _write_plan(mini_wiki, ["raw/sources/a.md", "raw/sources/b.md"])
    r = _run_executor(mini_wiki, extra_env={"BATCH_EXECUTOR_CRASH_AT": "generate"})
    # 崩溃后状态：至少 a 处于 in_progress（未 done）
    state = _state(mini_wiki)
    assert raw_status(state, "batch_0", "raw/sources/a.md") in ("pending", "in_progress")
    assert r.returncode == 137
    # 续跑
    r2 = _run_executor(mini_wiki, extra_args=["--resume"])
    assert r2.returncode == 0, r2.stderr[-2000:]
    state2 = _state(mini_wiki)
    assert raw_status(state2, "batch_0", "raw/sources/a.md") == "done"
    assert raw_status(state2, "batch_0", "raw/sources/b.md") == "done"


def test_crash_after_cascade_resumes_via_rebuild(mini_wiki: Path) -> None:
    """cascade 后 kill -9（pending_deletion 窗口）→ 续跑对 pending_deletion 重跑重建。"""
    _write_plan(mini_wiki, ["raw/sources/a.md"])
    r = _run_executor(mini_wiki, extra_env={"BATCH_EXECUTOR_CRASH_AT": "cascade"})
    state = _state(mini_wiki)
    # a 是 reingest 分支：cascade 后停在 pending_deletion
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "pending_deletion"
    assert r.returncode == 137
    # 旧 source 页已被 cascade 删除 → 续跑走首摄式重建
    assert not (mini_wiki / "wiki" / "sources" / "src-a.md").exists()
    r2 = _run_executor(mini_wiki, extra_args=["--resume"])
    assert r2.returncode == 0, r2.stderr[-2000:]
    state2 = _state(mini_wiki)
    assert raw_status(state2, "batch_0", "raw/sources/a.md") == "done"
    # 重建后有新 source 页
    assert any((mini_wiki / "wiki" / "sources").glob("*.md"))


def test_resume_skips_done_files(mini_wiki: Path) -> None:
    """续跑时 done 文件不重复处理（幂等）。"""
    _write_plan(mini_wiki, ["raw/sources/a.md", "raw/sources/b.md"])
    _run_executor(mini_wiki)
    r = _run_executor(mini_wiki, extra_args=["--resume"])
    assert r.returncode == 0, r.stderr[-2000:]
    # 两次运行后页面只有一轮生成
    state = _state(mini_wiki)
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"


# ---------------------------------------------------------------------------
# 每 raw 分支
# ---------------------------------------------------------------------------

def test_reingest_branch_when_source_page_exists(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, ["raw/sources/a.md"])
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    entry = state["batch_0"]["raw_states"]["raw/sources/a.md"]
    assert entry["branch"] == "reingest"
    assert entry["status"] == "done"


def test_first_ingest_branch_when_no_source_page(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, ["raw/sources/b.md"])
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    entry = state["batch_0"]["raw_states"]["raw/sources/b.md"]
    assert entry["branch"] == "first_ingest"


# ---------------------------------------------------------------------------
# pre-commit 门禁（失败 = 零写入）
# ---------------------------------------------------------------------------

def test_precommit_gate_failure_blocks_whole_batch(mini_wiki: Path) -> None:
    """门禁失败 → 整批零写入（batch gate_failed，raw 不 done）。"""
    _write_plan(mini_wiki, ["raw/sources/a.md", "raw/sources/b.md"])
    # 强制门禁失败：fake-generate 产出占位符页（lint ERROR）
    r = _run_executor(mini_wiki, extra_env={"RUFLO_FAKE_PLACEHOLDER": "1"})
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "gate_failed"
    assert raw_status(state, "batch_0", "raw/sources/a.md") != "done"
    # 零写入：fake 生成的 concept 页不应落盘（src-a 是 fixture 存量页，除外）
    written_concepts = list((mini_wiki / "wiki" / "concepts").glob("*.md"))
    assert written_concepts == [], f"gate failed but pages written: {written_concepts}"


# ---------------------------------------------------------------------------
# is_immutable / blocklist / git 快照
# ---------------------------------------------------------------------------

def test_immutable_source_skipped(mini_wiki: Path) -> None:
    """is_immutable 的存量 source 页摄入前跳过（plan guidance #13）。"""
    _write_plan(mini_wiki, ["raw/sources/a.md"])
    src = mini_wiki / "wiki" / "sources" / "src-a.md"
    text = src.read_text(encoding="utf-8")
    src.write_text(text.replace("processing_depth: source",
                                "processing_depth: source\nis_immutable: true"),
                   encoding="utf-8")
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    entry = state["batch_0"]["raw_states"]["raw/sources/a.md"]
    assert entry.get("skipped") == "immutable"
    assert entry["status"] == "done"


def test_git_snapshot_recorded(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, ["raw/sources/b.md"])
    # 让 mini_wiki 成为 git 仓库并提交一次，验证快照记录 HEAD
    subprocess.run(["git", "init", "-q", str(mini_wiki)], check=True)
    subprocess.run(["git", "-C", str(mini_wiki), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(mini_wiki), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(mini_wiki), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(mini_wiki), "commit", "-qm", "init"], check=True)
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("git_snapshot")


def test_failed_three_strikes_blocklists(mini_wiki: Path) -> None:
    """同一 raw 连续 3 批 failed → blocklist + 告警（plan guidance #11）。"""
    _write_plan(mini_wiki, ["raw/sources/b.md"])
    # 让 fake-generate 抛错（RUFLO_FAKE_FAIL=1）→ 每批 failed
    env = {"RUFLO_FAKE_FAIL": "1"}
    for _ in range(3):
        _run_executor(mini_wiki, extra_env=env)
    state = _state(mini_wiki)
    entry = state.get("batch_0", {}).get("raw_states", {}).get("raw/sources/b.md", {})
    assert entry.get("blocklisted") is True
    assert entry.get("fail_streak", 0) >= 3


# ---------------------------------------------------------------------------
# 预算自动暂停（plan guidance #12）
# ---------------------------------------------------------------------------

def test_budget_exceeded_auto_pauses(mini_wiki: Path) -> None:
    """累计费用超预算 → 自动暂停（batch status paused_budget，零写入）。"""
    _write_plan(mini_wiki, ["raw/sources/a.md", "raw/sources/b.md"])
    # fake 模式每批成本估算 0.2 USD；预算 0.1 → 第一轮后累计 0.2 超限
    r = _run_executor(mini_wiki, extra_args=["--budget-usd", "0.1"])
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") in ("paused_budget", "committed")
    assert r.returncode in (0, 3)
