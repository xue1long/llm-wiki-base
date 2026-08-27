"""Tests for Wiki rebuild dry-run script (B-3.5 commit 1).

路线 v2.2 §B-3.5 — spec §17 D-18 + Z-2 "Wiki 可在空视图存储上完全重建"
dry-run 演练. 本测试验证:

1. dry-run 脚本扫描 wiki/**/*.md + 返回 WikiRebuildDryrunResult
2. legacy 页面 (workflow_state != 'verified') 计数正确
3. verified 页面 → quality_score 高 (pass), not_evaluable=False
4. 空 wiki 目录 → wiki_pages_scanned=0, not_evaluable=False (无数据不算)

不在 src/ 业务代码中改任何东西; 仅测试 scripts/kc_wiki_rebuild_dryrun.py 的
纯函数输出 + 报告生成.

Ref: docs/architecture/B-2_11_Gate_design.md + spec §17 D-18 + Z-2.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "kc_wiki_rebuild_dryrun.py"

# 项目根中可直接 import 脚本模块 (REPO_ROOT 已被 conftest.py 注入 sys.path)
# 但 scripts/ 不是 package (无 __init__.py), 故用 importlib 直接加载
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_dryrun_module():
    """通过 importlib 加载 scripts/kc_wiki_rebuild_dryrun.py (scripts/ 无 __init__)."""
    import importlib.util

    mod_name = "kc_wiki_rebuild_dryrun"
    spec = importlib.util.spec_from_file_location(mod_name, str(SCRIPT))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # 注册到 sys.modules (避免 dataclass __module__ 异常)
    spec.loader.exec_module(mod)
    return mod


def _make_page(
    page_id: str,
    workflow_state: str = "verified",
    *,
    with_relation_legacy: bool = False,
    has_text: bool = True,
) -> str:
    """构造 mock markdown frontmatter + body."""
    rel_block = ""
    if with_relation_legacy:
        rel_block = "\nrelations:\n  - {type: implements, target_id: target_x}"

    text_block = f"\n\nbody text for {page_id}" if has_text else ""
    return (
        f"---\n"
        f"id: {page_id}\n"
        f"title: {page_id}\n"
        f"type: concept\n"
        f"workflow_state: {workflow_state}\n"
        f"{rel_block}"
        f"---\n"
        f"{text_block}"
    )


def _make_project(
    root: Path,
    pages: Iterable[tuple[str, str, bool, bool]],
) -> Path:
    """在 root 下创建 wiki/ + mock pages. 每个 tuple =
    (page_id, workflow_state, with_relation_legacy, has_text)."""
    wiki = root / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "entities").mkdir(parents=True)

    for page_id, state, legacy, text in pages:
        if state == "verified":
            sub = "concepts"
        else:
            sub = "entities"
        (wiki / sub / f"{page_id}.md").write_text(
            _make_page(page_id, state, with_relation_legacy=legacy, has_text=text),
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# Test 1: dry-run 扫描 5 个 WikiPage → wiki_pages_scanned=5
# ---------------------------------------------------------------------------
def test_dryrun_scans_five_wiki_pages(tmp_path: Path) -> None:
    """在 tmp_path 创建 5 个 verified/legacy wiki 页, run_dryrun 应返回 5 pages."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    pages = [
        ("p1", "verified", False, True),
        ("p2", "verified", False, True),
        ("p3", "verified", False, True),
        ("p4", "draft", False, True),
        ("p5", "draft", False, True),
    ]
    _make_project(tmp_path, pages)

    result = run_dryrun(tmp_path, max_pages=50)

    assert result.wiki_pages_scanned == 5
    assert isinstance(result.project_root, Path)
    # integrity_reports 截取前 5 个样本
    assert len(result.integrity_reports) == 5
    # sample_rendered_hashes 包含所有 page_id
    assert set(result.sample_rendered_hashes.keys()) == {"p1", "p2", "p3", "p4", "p5"}


# ---------------------------------------------------------------------------
# Test 2: 10 个 legacy 页面 → legacy_pages_count=10
# ---------------------------------------------------------------------------
def test_dryrun_counts_legacy_pages(tmp_path: Path) -> None:
    """10 个 legacy (workflow_state != 'verified') 页面 → legacy_pages_count=10."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    pages = [
        (f"legacy{i}", "draft", False, True)
        for i in range(10)
    ]
    _make_project(tmp_path, pages)

    result = run_dryrun(tmp_path, max_pages=50)

    assert result.legacy_pages_count == 10
    assert result.wiki_pages_scanned == 10
    # would_block_pages >= 0 (legacy 不一定 block, 但 should not crash)
    assert result.would_block_pages >= 0
    assert result.would_warn_pages >= 0


# ---------------------------------------------------------------------------
# Test 3: 5 个 verified 页面 → quality_score > 0.9, not_evaluable=False
# ---------------------------------------------------------------------------
def test_dryrun_verified_pages_high_quality_score(tmp_path: Path) -> None:
    """5 个 verified 页面 (full frontmatter, no legacy rels) → quality_score 高."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    pages = [
        (f"verified{i}", "verified", False, True)
        for i in range(5)
    ]
    _make_project(tmp_path, pages)

    result = run_dryrun(tmp_path, max_pages=50)

    assert result.wiki_pages_scanned == 5
    # verified 页面应通过 Gate → quality_score 高 (默认 E-2 全 strong 时 ≥ 0.9)
    assert result.health_quality_score > 0.9
    # 有数据有 passed → not_evaluable=False
    assert result.not_evaluable is False
    # legacy 计数 0
    assert result.legacy_pages_count == 0


# ---------------------------------------------------------------------------
# Test 4: 空目录 → wiki_pages_scanned=0, not_evaluable=False
# ---------------------------------------------------------------------------
def test_dryrun_empty_wiki_returns_zero(tmp_path: Path) -> None:
    """空 wiki/ 目录 → wiki_pages_scanned=0, not_evaluable=False (无数据不算 NA)."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    # 只创建 wiki/ 目录但无 .md
    (tmp_path / "wiki").mkdir(parents=True)

    result = run_dryrun(tmp_path, max_pages=50)

    assert result.wiki_pages_scanned == 0
    assert result.not_evaluable is False
    assert result.legacy_pages_count == 0
    assert result.would_block_pages == 0
    assert result.would_warn_pages == 0
    assert result.sample_rendered_hashes == {}