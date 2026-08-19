"""Phase 4 并行生成/串行提交拆分的测试。

覆盖 scripts/batch_generate.py + scripts/batch_commit.py：
- generate 缓存可反序列化，commit 成功提交
- 多批次并行生成后串行提交
- 门禁失败 = 零写入
- 生成失败 raw 在 commit 阶段标记 failed
- cache 缺失时 commit 报错
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
    return load_batch_state(WikiPaths(root))


def _write_plan(root: Path, batches: list[list[str]]) -> None:
    plan_dir = root / ".index"
    plan_dir.mkdir(parents=True, exist_ok=True)
    files = [f for batch in batches for f in batch]
    plan = {
        "summary": {"raw_md_total": len(files)},
        "batches": [
            {"theme": f"test-{i}", "batch_no": i, "files": batch}
            for i, batch in enumerate(batches)
        ],
    }
    (plan_dir / "reingest_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    """A tiny wiki with two raws."""
    ensure_knowledge_base(tmp_path)
    raw = tmp_path / "raw" / "sources"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "a.md").write_text("# 素材A\n\n内容", encoding="utf-8")
    (raw / "b.md").write_text("# 素材B\n\n内容", encoding="utf-8")
    (raw / "c.md").write_text("# 素材C\n\n内容", encoding="utf-8")
    (raw / "d.md").write_text("# 素材D\n\n内容", encoding="utf-8")
    return tmp_path


def _run_generate(root: Path, batches: str, *,
                  extra_env: dict | None = None,
                  extra_args: list[str] | None = None,
                  timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["RUFLO_EXECUTOR_FAKE_GENERATE"] = "1"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "batch_generate.py"),
           "--root", str(root), "--batches", batches,
           "--manifest", str(root / ".index" / "reingest_plan.json"),
           "--concurrency", "2", "--batch-concurrency", "2"]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=timeout, cwd=str(REPO_ROOT))


def _run_commit(root: Path, batches: str, *,
                extra_env: dict | None = None,
                extra_args: list[str] | None = None,
                timeout: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["RUFLO_EXECUTOR_FAKE_GENERATE"] = "1"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    env.pop("http_proxy", None)
    env.pop("https_proxy", None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "batch_commit.py"),
           "--root", str(root), "--batches", batches,
           "--manifest", str(root / ".index" / "reingest_plan.json")]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=timeout, cwd=str(REPO_ROOT))


def _cache(root: Path, batch_no: int) -> dict | None:
    p = root / ".index" / "generated_cache" / f"batch_{batch_no}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_generate_then_commit_single_batch(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [["raw/sources/a.md", "raw/sources/b.md"]])
    r = _run_generate(mini_wiki, "0")
    assert r.returncode == 0, r.stderr[-2000:]
    cache = _cache(mini_wiki, 0)
    assert cache is not None
    assert len(cache["files"]) == 2
    assert all(e["status"] == "generated" for e in cache["files"])
    assert all(e["pages"] for e in cache["files"])
    assert all("meta" in e for e in cache["files"])

    # 此时未写 wiki（zero disk writes）
    concepts = list((mini_wiki / "wiki" / "concepts").glob("*.md"))
    assert concepts == []

    r2 = _run_commit(mini_wiki, "0")
    assert r2.returncode == 0, r2.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "committed"
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"
    assert raw_status(state, "batch_0", "raw/sources/b.md") == "done"
    assert list((mini_wiki / "wiki" / "concepts").glob("*.md"))


def test_generate_parallel_batches_then_commit_serially(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [
        ["raw/sources/a.md", "raw/sources/b.md"],
        ["raw/sources/c.md", "raw/sources/d.md"],
    ])
    r = _run_generate(mini_wiki, "0-1")
    assert r.returncode == 0, r.stderr[-2000:]
    assert _cache(mini_wiki, 0) is not None
    assert _cache(mini_wiki, 1) is not None

    r2 = _run_commit(mini_wiki, "0,1")
    assert r2.returncode == 0, r2.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "committed"
    assert state.get("batch_1", {}).get("status") == "committed"
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "done"
    assert raw_status(state, "batch_1", "raw/sources/c.md") == "done"


def test_commit_idempotent_after_done(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [["raw/sources/a.md"]])
    assert _run_generate(mini_wiki, "0").returncode == 0
    assert _run_commit(mini_wiki, "0").returncode == 0
    # 再次 commit 应跳过 done，不重复写盘
    r = _run_commit(mini_wiki, "0")
    assert r.returncode == 0, r.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "committed"


# ---------------------------------------------------------------------------
# Gate failure / generation failure
# ---------------------------------------------------------------------------

def test_commit_gate_failure_blocks_zero_write(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [["raw/sources/a.md", "raw/sources/b.md"]])
    # fake 生成带占位符 → pre-commit lint ERROR
    r = _run_generate(mini_wiki, "0", extra_env={"RUFLO_FAKE_PLACEHOLDER": "1"})
    assert r.returncode == 0, r.stderr[-2000:]
    r2 = _run_commit(mini_wiki, "0")
    assert r2.returncode == 2, r2.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "gate_failed"
    # 零写入：fake concept 页不应落盘
    assert list((mini_wiki / "wiki" / "concepts").glob("*.md")) == []


def test_generate_failure_marks_failed_on_commit(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [["raw/sources/a.md", "raw/sources/b.md"]])
    r = _run_generate(mini_wiki, "0", extra_env={"RUFLO_FAKE_FAIL": "1"})
    assert r.returncode == 2, r.stderr[-2000:]  # 部分失败
    cache = _cache(mini_wiki, 0)
    assert all(e["status"] == "failed" for e in cache["files"])

    r2 = _run_commit(mini_wiki, "0")
    # 全部 failed → BATCH ABORTED，exit 1
    assert r2.returncode == 1, r2.stderr[-2000:]
    state = _state(mini_wiki)
    assert state.get("batch_0", {}).get("status") == "failed"
    assert raw_status(state, "batch_0", "raw/sources/a.md") == "failed"


def test_commit_missing_cache_errors(mini_wiki: Path) -> None:
    _write_plan(mini_wiki, [["raw/sources/a.md"]])
    r = _run_commit(mini_wiki, "0")
    assert r.returncode == 1
    assert "CACHE MISS" in r.stdout


# ---------------------------------------------------------------------------
# Cache serialization round-trip
# ---------------------------------------------------------------------------

def test_cache_roundtrip_preserves_page_fields(mini_wiki: Path) -> None:
    from scripts.batch_generate import _page_from_dict
    _write_plan(mini_wiki, [["raw/sources/a.md"]])
    assert _run_generate(mini_wiki, "0").returncode == 0
    cache = _cache(mini_wiki, 0)
    entry = cache["files"][0]
    for pd in entry["pages"]:
        page = _page_from_dict(pd)
        assert page.id
        assert page.title
        assert page.type.value in ("source", "concept", "entity", "synthesis")
        assert page.body
