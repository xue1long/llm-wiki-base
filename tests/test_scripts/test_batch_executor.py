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


def _reset_raw_state(root: Path, raw: str) -> None:
    """测试辅助：把 raw 状态重置为 pending（下次运行重新处理）。"""
    p = root / ".index" / "batch_build_state.json"
    state = json.loads(p.read_text(encoding="utf-8"))
    state["batch_0"]["raw_states"][raw] = {"status": "pending", "fail_streak": 0}
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def test_toctou_write_conflict_refuses_overwrite(mini_wiki: Path) -> None:
    """Task 0.3：generate 后目标页被人工修改 → WRITE-CONFLICT，拒绝覆盖。

    第一轮提交 b.md（生成 src-b + concept-b）；删除 src-b 使第二轮走
    first_ingest（无 cascade 删除），再注入 TOUCH 模拟 generate 与 commit
    之间的人工编辑 → commit 检测到 concept-b 内容变化，拒绝覆盖。
    """
    _write_plan(mini_wiki, ["raw/sources/b.md"])
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    assert (mini_wiki / "wiki" / "concepts" / "concept-b.md").exists()

    # 删除 source 页 → 下轮 first_ingest（concept 页仍是存量目标）
    (mini_wiki / "wiki" / "sources" / "src-b.md").unlink()
    _reset_raw_state(mini_wiki, "raw/sources/b.md")

    r2 = _run_executor(
        mini_wiki,
        extra_env={"RUFLO_EXECUTOR_TOUCH_RAW": "raw/sources/b.md"},
    )
    assert r2.returncode != 0, r2.stderr[-2000:]
    state = _state(mini_wiki)
    entry = state["batch_0"]["raw_states"]["raw/sources/b.md"]
    assert entry["status"] == "failed"
    assert "WRITE-CONFLICT" in entry.get("last_error", ""), entry
    # 人工编辑未被静默覆盖
    assert "<!-- manual edit -->" in (
        mini_wiki / "wiki" / "concepts" / "concept-b.md"
    ).read_text(encoding="utf-8")


def test_partial_commit_records_state_and_resume_retries(mini_wiki: Path) -> None:
    """Task 0.2：单 raw flush 部分失败 → partial_commit + 停止后续；续跑幂等重试。

    注入 RUFLO_FLUSH_FAIL_PATHS 让 b.md 的 source 页 flush 失败。先提交
    a.md（前序已写），再让 b.md 部分失败，制造真实"前序成功 + 后序部分
    提交"的中间态。
    """
    # 1) 先提交 a.md
    _write_plan(mini_wiki, ["raw/sources/a.md"])
    r = _run_executor(mini_wiki)
    assert r.returncode == 0, r.stderr[-2000:]
    assert raw_status(_state(mini_wiki), "batch_0", "raw/sources/a.md") == "done"

    # 2) b.md 提交时注入 flush 失败 → partial_commit + 停止（rc 4）
    _write_plan(mini_wiki, ["raw/sources/b.md"])
    r = _run_executor(mini_wiki, extra_env={"RUFLO_FLUSH_FAIL_PATHS": "src-b.md"})
    assert r.returncode == 4, r.stderr[-2000:]
    state = _state(mini_wiki)
    b_entry = state["batch_0"]["raw_states"]["raw/sources/b.md"]
    assert b_entry["status"] == "partial_commit"
    assert any("src-b.md" in p for p in b_entry.get("failed_paths", []))
    assert state["batch_0"]["status"] == "partial_commit"
    # 部分提交：同批 concept 页已写出，但 source 页失败（真实中间态）
    assert (mini_wiki / "wiki" / "concepts" / "concept-b.md").exists()
    assert not (mini_wiki / "wiki" / "sources" / "src-b.md").exists()

    # 3) 恢复后续跑：幂等重试，page/index/log 不重复
    r2 = _run_executor(mini_wiki, extra_args=["--resume"])
    assert r2.returncode == 0, r2.stderr[-2000:]
    state2 = _state(mini_wiki)
    assert raw_status(state2, "batch_0", "raw/sources/b.md") == "done"
    assert state2["batch_0"]["status"] == "committed"
    assert (mini_wiki / "wiki" / "sources" / "src-b.md").exists()
    # 每个页面在索引中恰好出现一次（重试不重复追加）
    index_after = (mini_wiki / "wiki" / "index.md").read_text(encoding="utf-8")
    for slug in ("src-a", "concept-a", "src-b", "concept-b"):
        assert index_after.count(f"**{slug}**") == 1, f"duplicate index entry: {slug}"




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
    # 让 fake-generate 抛错（RUFLO_FAKE_FAIL=1）→ 每批 failed。
    # --resume 语义（M1 review）：failed 只在续跑时重投，续跑累计 3 次触发。
    env = {"RUFLO_FAKE_FAIL": "1"}
    for i in range(3):
        _run_executor(mini_wiki, extra_env=env,
                      extra_args=["--resume"] if i > 0 else None)
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


# ---------------------------------------------------------------------------
# pre-commit gate 真实路径（review C2/C3/I4：WikiPage relations / operation
# depth / v3.0.0 synthesis 不误杀、不崩溃）
# ---------------------------------------------------------------------------

@pytest.fixture
def gate_wiki(tmp_path: Path) -> Path:
    """带项目级 v3.0.0 模板的 wiki（synthesis conclusion 槽 → 待定与结论）。"""
    ensure_knowledge_base(tmp_path)
    tpl = tmp_path / ".wiki-templates"
    tpl.mkdir(parents=True, exist_ok=True)
    proj = REPO_ROOT / "knowledge" / "novel-wiki" / ".wiki-templates"
    for name in ("source.md", "concept.md", "entity.md", "synthesis.md"):
        if (proj / name).exists():
            (tpl / name).write_text(
                (proj / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def _mk_page(wiki_root: Path, rel: str, body: str,
             depth: str = "concept", tags: list[str] | None = None) -> None:
    p = wiki_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    page_id = Path(rel).stem
    fm = [f"id: {page_id}", f"title: {page_id}",
          "type: " + ("source" if "/sources/" in rel else "concept"),
          "sources:\n- raw/sources/a.md", f"processing_depth: {depth}"]
    if tags:
        fm.append("tags:")
        fm.extend(f"- {t}" for t in tags)
    p.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body, encoding="utf-8")
    # 对账口径读 wiki/index.md —— 落盘页必须经 append_to_index 登记
    from src.wiki.core.paths import WikiPaths as _WP
    from src.wiki.features.indexer import append_to_index
    from src.wiki.core.types import PageType as _PT
    ptype = _PT.SOURCE if "/sources/" in rel else _PT.CONCEPT
    append_to_index(_WP(wiki_root), [(page_id, ptype, page_id)])


def test_gate_accepts_wikipage_with_relations_and_operation_depth(gate_wiki) -> None:
    """C2：WikiPage.relations 是 Relation dataclass（非 dict）——gate 不崩溃。"""
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.wiki.features.batch_gate import run_precommit_gate
    from src.wiki.core.types import Relation, WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    # 目标页必须存在（对账口径：磁盘 ∪ produced）
    _mk_page(gate_wiki, "wiki/sources/src-a.md",
             "<!-- wiki-template-version: 3.0.0 -->\n## 摘要\n\ns\n",
             depth="source")
    _mk_page(gate_wiki, "wiki/concepts/concept-b.md",
             "<!-- wiki-template-version: 3.0.0 -->\n## 定义\n\nd\n",
             depth="concept")

    page = WikiPage(
        id="synthesis-执梦", title="执梦", type=PageType.SYNTHESIS,
        sources=["raw/sources/a.md"], processing_depth="operation", grade="B",
        body=(
            "<!-- wiki-template-version: 3.0.0 -->\n"
            "<!-- wiki-template-type: synthesis -->\n\n"
            "## 议题与分歧点\n\n议题\n\n## 各方观点\n\n- [[src-a]]\n- [[concept-b]]\n\n"
            "## 共识\n\n共识\n\n## 证据对比\n\n对比\n\n## 待定与结论\n\n结论\n"),
        relations=[Relation(type="derived_from", target_id="src-a", weight=1.0)],
    )
    paths = WikiPaths(gate_wiki)
    passed, issues = run_precommit_gate([page], [], {}, paths)
    # operation depth 合法；v3.0.0 synthesis 的 待定与结论 槽命中（非 结论）
    assert passed, issues
    assert not any("invalid processing_depth" in i for i in issues)
    assert not any("MISSING-SECTION" in i for i in issues)


def test_gate_rejects_placeholder_and_illegal_relation(gate_wiki) -> None:
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.wiki.features.batch_gate import run_precommit_gate
    from src.wiki.core.types import Relation, WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    bad = WikiPage(
        id="bad-1", title="坏页", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n待补充\n",
        relations=[Relation(type="related_to", target_id="x", weight=1.0)],
    )
    paths = WikiPaths(gate_wiki)
    passed, issues = run_precommit_gate([bad], [], {}, paths)
    assert not passed
    assert any("LINT-PLACEHOLDER" in i for i in issues)
    assert any("LINT-ILLEGAL-RELATION" in i for i in issues)


def test_gate_accepts_valid_tags_and_rejects_invalid(gate_wiki) -> None:
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.wiki.features.batch_gate import run_precommit_gate
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths
    paths = WikiPaths(gate_wiki)
    _mk_page(gate_wiki, "wiki/sources/src-a.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 摘要\n\ns\n",
             depth="source")
    _mk_page(gate_wiki, "wiki/concepts/c.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 定义\n\nd\n",
             depth="concept")

    clean = WikiPage(
        id="clean-1", title="干净", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
             "## 主要特点\n\n- x\n\n## 例子\n\n- y\n\n## 相关概念\n\n[[c]]\n\n"
             "## 参考来源\n\n[[src-a]]\n",
        tags=["素材/ugc", "可信度/ugc"],
    )
    passed, issues = run_precommit_gate([clean], [], {}, paths)
    assert passed, issues

    bad_tags = WikiPage(
        id="bad-tag", title="坏标签", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body=clean.body, tags=["读者群/其它"],
    )
    passed2, issues2 = run_precommit_gate([bad_tags], [], {}, paths)
    assert not passed2
    assert any("TAG-ENUM" in i for i in issues2)


# ---------------------------------------------------------------------------
# Phase 4 试跑实测缺陷回归（2026-08-16 batch 0 全量试跑暴露）：
#   A. gap 账本在 batch 路径未落盘 → pre-commit 门禁把本应豁免的
#      本批新 gap 链接误判 BROKEN-LINK（零写入误拦整批）；
#   B. extras（存量 reverse-touch 页）被新规范 tags/lint 误拦——
#      存量旧英文 tag（func/genre/mood）是 M8 消解范围，不计入批内判定。
# ---------------------------------------------------------------------------

def test_precommit_gate_exempts_batch_pending_gap_slugs(gate_wiki) -> None:
    """A：本批 generate 已采集的 missing_slugs 必须豁免 BROKEN-LINK。

    试跑根因：_commit_raw 丢弃 meta['missing_slugs'] → gap 从未落盘；
    且门禁在 commit 前运行，磁盘 gap 不含本批新增 → 误拦。修复后
    run_precommit_gate 接收本批 pending gap slugs 并入豁免集。
    """
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.wiki.features.batch_gate import run_precommit_gate
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(gate_wiki)
    _mk_page(gate_wiki, "wiki/sources/src-a.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 摘要\n\ns\n",
             depth="source")
    _mk_page(gate_wiki, "wiki/concepts/c.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 定义\n\nd\n",
             depth="concept")

    # 本批新页引用两个目标：c（可解析）+ ghost-1（本批已采集 pending gap）
    page = WikiPage(
        id="p1", title="批内页", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
             "## 主要特点\n\n- x\n\n## 例子\n\n[[ghost-1]]\n\n"
             "## 相关概念\n\n[[c]]\n\n## 参考来源\n\n[[src-a]]\n",
        tags=["素材/ugc", "可信度/ugc"],
    )
    # 未传 pending gap → ghost-1 判 BROKEN-LINK
    passed, issues = run_precommit_gate([page], [], {}, paths)
    assert not passed
    assert any("BROKEN-LINK" in i and "ghost-1" in i for i in issues)

    # 传入本批 pending gap slugs → 豁免（与磁盘 gap 同口径）
    passed2, issues2 = run_precommit_gate(
        [page], [], {}, paths, pending_gap_slugs={"ghost-1"})
    assert passed2, issues2
    assert not any("BROKEN-LINK" in i for i in issues2)


def test_precommit_gate_ignores_legacy_tags_and_links_on_extras(gate_wiki) -> None:
    """B：extras（存量 reverse-touch 页）不参与 fields/tags/lint 检查。

    试跑根因：三章亮卖点法则/新人作者心态调整/悬念设置 是存量 2.0.0 页
    （旧英文 tag func/genre/mood + 历史断链），被 reverse-touch 成 extras
    后遭新规范误拦。按 phase3_accept 口径 extras 不计入批内 M1/M4/M9。
    """
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.wiki.features.batch_gate import run_precommit_gate
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    paths = WikiPaths(gate_wiki)
    _mk_page(gate_wiki, "wiki/sources/src-a.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 摘要\n\ns\n",
             depth="source")

    # 存量 extras：旧英文 tag + 历史断链（M8/M1 消解范围，本批只补反向边）
    legacy_extra = WikiPage(
        id="三章亮卖点法则", title="三章亮卖点法则", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
             "## 例子\n\n[[金手指]]\n",
        tags=["func/法则", "genre/网文", "scene_phase/开篇", "mood/期待感"],
    )
    clean = WikiPage(
        id="new-1", title="新页", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
             "## 主要特点\n\n- x\n\n## 例子\n\n- y\n\n"
             "## 相关概念\n\n[[三章亮卖点法则]]\n\n## 参考来源\n\n[[src-a]]\n",
        tags=["素材/ugc", "可信度/ugc"],
    )
    # 修复前：extras 的旧 tag + 断链 → TAG-ENUM + BROKEN-LINK 误拦整批
    passed, issues = run_precommit_gate([clean], [legacy_extra], {}, paths)
    assert passed, issues
    assert not any("TAG-ENUM" in i for i in issues)
    assert not any("BROKEN-LINK" in i for i in issues)


def test_commit_raw_persists_missing_slugs_to_gap_ledger(mini_wiki: Path) -> None:
    """A 全链路：_commit_raw 透传 meta['missing_slugs'] → KnowledgeGapStore 落盘。

    试跑根因：_commit_raw 丢弃 meta → batch 路径 gap 账本从未写入（磁盘
    只有存量条目），门禁读不到本批 gap → BROKEN-LINK 误拦整批。此测试
    断言 commit 后 knowledge_gaps.json 包含本批新增 slug。
    """
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    import asyncio
    from src.orchestrator.batch_runner import _commit_raw
    from src.wiki.core.types import WikiPage, PageType

    raw_rel = "raw/sources/b.md"   # 无存量 source 页 → first_ingest 分支
    page = WikiPage(
        id="src-b", title="源B", type=PageType.SOURCE,
        sources=[raw_rel], processing_depth="source", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 摘要\n\n内容\n",
    )
    meta = {"missing_slugs": [{"slug": "ghost-落盘", "referenced_by": ["src-b"]}]}

    async def _run() -> None:
        from src.wiki.core.paths import WikiPaths
        from src.wiki.features.knowledge_gaps import KnowledgeGapStore
        paths = WikiPaths(mini_wiki)
        await _commit_raw(paths, raw_rel, [page], [], "batch_0",
                          task_id="t-1", meta=meta)
        gaps = {g.slug for g in KnowledgeGapStore(mini_wiki).all()}
        assert "ghost-落盘" in gaps, f"gap ledger missing new slug: {gaps}"

    asyncio.run(_run())


def test_auto_tag_ugc_tags_carrier_derived_pages(gate_wiki: Path) -> None:
    """C：UGC carrier raw 派生页在门禁前被确定性补 素材/ugc + 可信度/ugc。

    试跑根因：batch_executor 缺 phase4_batch 的 R3-1/F2 auto-tag 步骤 →
    NDG P4b 把 UGC 派生页缺 tag 列为 blocker → 整批零写入误拦。
    """
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from src.orchestrator.batch_runner import _auto_tag_ugc
    from src.wiki.core.types import WikiPage, PageType

    # UGC carrier header（lint _is_ugc_carrier 命中：QQ 群/分享 等特征）
    carrier_header = (
        "小白作者网文大学 QQ群 分享文件 写作教程 素材"
    )
    page = WikiPage(
        id="src-ugc", title="源UGC", type=PageType.SOURCE,
        sources=["raw/sources/ugc.md"], processing_depth="source", grade="B",
        body="## 摘要\n\n内容\n", tags=[],
    )
    n = _auto_tag_ugc([page], {"raw/sources/ugc.md": carrier_header})
    assert n == 1
    assert "素材/ugc" in page.tags and "可信度/ugc" in page.tags

    # 非 UGC carrier → 不动
    page2 = WikiPage(
        id="src-plain", title="源普通", type=PageType.SOURCE,
        sources=["raw/sources/plain.md"], processing_depth="source", grade="B",
        body="## 摘要\n\n内容\n", tags=[],
    )
    n2 = _auto_tag_ugc([page2], {"raw/sources/plain.md": "普通文档内容"})
    assert n2 == 0
    assert page2.tags == []


def test_rerun_gate_batch_filters_to_batch_pages(gate_wiki: Path) -> None:
    """E：整批复核只查本批新写页，跳过存量 extras（M8/M9 消解范围）。

    试跑根因：reverse-touch 把存量页（东方玄幻，含历史非法 relation
    contrasts）写回为 extras，旧 _rerun_gate_batch 按 source 关联全扫 →
    存量非法 relation 使整批 gate_recheck_failed。修复后 page_ids 过滤
    只复核本批 pages。
    """
    import sys as _sys
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    import asyncio
    from src.orchestrator.batch_runner import _rerun_gate_batch
    from src.wiki.core.types import Relation, WikiPage, PageType
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import write_page

    paths = WikiPaths(gate_wiki)
    # 目标 source 页（对账口径：磁盘 ∪ produced 需可解析，_mk_page 会
    # append_to_index 登记到 wiki/index.md）
    _mk_page(gate_wiki, "wiki/sources/src-a.md",
             "<!-- wiki-template-version: 2.0.0 -->\n## 摘要\n\ns\n",
             depth="source")
    # 磁盘存量页（reverse-touch extras）：历史非法 relation contrasts
    # （不在 17 内置 + 非 x-），M9 消解范围，不应在整批复核被拦。
    legacy = WikiPage(
        id="东方玄幻", title="东方玄幻", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], processing_depth="concept", grade="B",
        body="<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
             "## 主要特点\n\n- x\n\n## 例子\n\n- y\n",
        tags=["素材/ugc", "可信度/ugc"],
        relations=[Relation(type="contrasts", target_id="仙侠小说")],
    )
    write_page(paths, legacy)

    # 本批新页（干净；_mk_page 登记 index，body 引用 src-a 可解析）
    _mk_page(
        gate_wiki, "wiki/concepts/new-page.md",
        "<!-- wiki-template-version: 2.0.0 -->\n\n## 定义\n\n内容\n\n"
        "## 主要特点\n\n- x\n\n## 例子\n\n- y\n\n"
        "## 相关概念\n\n[[src-a]]\n\n## 参考来源\n\n[[src-a]]\n",
        depth="concept", tags=["素材/ugc", "可信度/ugc"],
    )

    async def _run() -> None:
        # 只复核本批新页 → 存量 extras 不拦
        ok = await _rerun_gate_batch(
            paths, "batch_0", ["raw/sources/a.md"],
            batch_page_ids=["new-page"])
        assert ok is True

        # 旧行为（无 page_ids / 含存量页）→ 非法 relation 被拦
        ok2 = await _rerun_gate_batch(
            paths, "batch_0", ["raw/sources/a.md"],
            batch_page_ids=["new-page", "东方玄幻"])
        assert ok2 is False

    asyncio.run(_run())
