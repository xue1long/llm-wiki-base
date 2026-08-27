"""Tests for Book rebuild dry-run script (B-3.6 commit 1).

路线 v2.2 §B-3.6 — spec §14 A8 + §17 D-18 + Z-4 "Book 可在空视图存储上
完全重建" dry-run 演练. 本测试验证:

1. 2 books / 5 chapters → book_count=2, chapter_count=5
2. 3 legacy chapters (workflow_state != 'verified') → legacy_chapters_count=3
3. empty project → book_count=0, six_principles_check 全部 True
4. 5 verified chapters → quality_score > 0.9, not_evaluable=False

不在 src/ 业务代码中改任何东西; 仅测试 scripts/kc_book_rebuild_dryrun.py
纯函数输出 + 报告生成.

Ref: docs/architecture/B-2_11_Gate_design.md + spec §14 A8 + §17 D-18 + §12.5 + Z-4.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS_DIR / "kc_book_rebuild_dryrun.py"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_dryrun_module():
    """通过 importlib 加载 scripts/kc_book_rebuild_dryrun.py (scripts/ 无 __init__)."""
    mod_name = "kc_book_rebuild_dryrun"
    spec = importlib.util.spec_from_file_location(mod_name, str(SCRIPT))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_chapter(
    chapter_id: str,
    workflow_state: str = "verified",
    *,
    has_text: bool = True,
) -> str:
    """构造 mock markdown frontmatter + body (Book Chapter)."""
    text_block = f"\n\nbody text for {chapter_id}" if has_text else ""
    return (
        f"---\n"
        f"id: {chapter_id}\n"
        f"title: {chapter_id}\n"
        f"type: concept\n"
        f"workflow_state: {workflow_state}\n"
        f"---\n"
        f"{text_block}"
    )


def _make_project(
    root: Path,
    books: Iterable[tuple[str, list[tuple[str, str, bool]]]],
) -> Path:
    """在 root 下创建 knowledge/books/ + mock books.

    books: iterable of (book_title, [(chapter_id, workflow_state, has_text), ...])
    """
    books_dir = root / "knowledge" / "books"
    for book_title, chapters in books:
        book_dir = books_dir / book_title
        book_dir.mkdir(parents=True, exist_ok=True)
        for chapter_id, state, has_text in chapters:
            (book_dir / f"{chapter_id}.md").write_text(
                _make_chapter(chapter_id, state, has_text=has_text),
                encoding="utf-8",
            )
    return root


# ---------------------------------------------------------------------------
# Test 1: 2 books / 5 chapters → book_count=2, chapter_count=5
# ---------------------------------------------------------------------------
def test_dryrun_scans_two_books_five_chapters(tmp_path: Path) -> None:
    """在 tmp_path 创建 2 books 含 5 总数 chapters, run_dryrun 应返回 book_count=2, chapter_count=5."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    books = [
        ("book_a", [
            ("ch_a1", "verified", True),
            ("ch_a2", "verified", True),
            ("ch_a3", "draft", True),
        ]),
        ("book_b", [
            ("ch_b1", "draft", True),
            ("ch_b2", "draft", True),
        ]),
    ]
    _make_project(tmp_path, books)

    result = run_dryrun(tmp_path, max_books=5)

    assert result.book_count == 2
    assert result.chapter_count == 5
    assert isinstance(result.project_root, Path)
    # book_structure 含 2 个 book
    assert set(result.book_structure.keys()) == {"book_a", "book_b"}
    # 5 个 chapter path
    all_paths = [p for paths in result.book_structure.values() for p in paths]
    assert len(all_paths) == 5


# ---------------------------------------------------------------------------
# Test 2: 3 legacy chapters → legacy_chapters_count=3
# ---------------------------------------------------------------------------
def test_dryrun_counts_legacy_chapters(tmp_path: Path) -> None:
    """3 legacy (workflow_state != 'verified') chapters → legacy_chapters_count=3."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    books = [
        ("book_a", [
            ("legacy1", "draft", True),
            ("legacy2", "draft", True),
            ("legacy3", "ready", True),
        ]),
    ]
    _make_project(tmp_path, books)

    result = run_dryrun(tmp_path, max_books=5)

    assert result.legacy_chapters_count == 3
    assert result.chapter_count == 3
    # would_block_chapters >= 0
    assert result.would_block_chapters >= 0
    assert result.would_warn_chapters >= 0


# ---------------------------------------------------------------------------
# Test 3: empty project → book_count=0, six_principles_check 全部 True
# ---------------------------------------------------------------------------
def test_dryrun_empty_project_returns_zero_with_six_principles(tmp_path: Path) -> None:
    """空项目 (无 knowledge/books/) → book_count=0, six_principles_check 全 True."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    # 不创建 knowledge/books/ 目录
    result = run_dryrun(tmp_path, max_books=5)

    assert result.book_count == 0
    assert result.chapter_count == 0
    assert result.legacy_chapters_count == 0
    assert result.would_block_chapters == 0
    assert result.would_warn_chapters == 0
    assert result.sample_chapter_hashes == {}
    assert result.book_structure == {}
    # spec §12.5 Book 6 项实现要点 - 全部 True
    assert result.six_principles_check == {
        "fixed_template": True,
        "stable_chapter_directory": True,
        "ku_to_chapter_mapping": True,
        "single_chapter_compile": True,
        "evidence_binding": True,
        "incremental_recompile": True,
    }


# ---------------------------------------------------------------------------
# Test 4: 5 verified chapters → quality_score > 0.9, not_evaluable=False
# ---------------------------------------------------------------------------
def test_dryrun_verified_chapters_high_quality_score(tmp_path: Path) -> None:
    """5 verified chapters (full frontmatter) → quality_score > 0.9, not_evaluable=False."""
    mod = _load_dryrun_module()
    run_dryrun = mod.run_dryrun

    books = [
        ("book_a", [
            (f"verified{i}", "verified", True)
            for i in range(5)
        ]),
    ]
    _make_project(tmp_path, books)

    result = run_dryrun(tmp_path, max_books=5)

    assert result.book_count == 1
    assert result.chapter_count == 5
    # verified 页面应通过 Gate → quality_score 高
    assert result.health_quality_score > 0.9
    assert result.not_evaluable is False
    assert result.legacy_chapters_count == 0
    # sample_chapter_hashes 含 5 个 chapter_path
    assert len(result.sample_chapter_hashes) == 5