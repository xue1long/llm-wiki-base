"""Phase 4.1 tests — plan_reingest_batches 全量分批清单生成.

Covers (plan Phase 4 guidance #1):
- 每批 ≤20 .md 文件（扩展名白名单）
- 排除 download_progress.json 等非文档文件
- 缺口优先：open gap 的 raw_hint 命中的 raw 排在最前
- 主题目录推进：剩余 raw 按目录序 + 文件名序稳定排列
- 清单覆盖全部 raw、无重复、无遗漏
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def mini_wiki(tmp_path: Path) -> Path:
    """A tiny wiki with raws across two theme dirs + a gap ledger."""
    dirs = {
        "raw/sources/01_新手入门": ["甲入门.md", "乙入门.md", "丙入门.md"],
        "raw/sources/02_进阶技巧": ["丁进阶.md", "戊进阶.md"],
    }
    for d, files in dirs.items():
        p = tmp_path / d
        p.mkdir(parents=True, exist_ok=True)
        for f in files:
            (p / f).write_text(f"# {f}\n内容", encoding="utf-8")
    # Non-md files must be excluded.
    (tmp_path / "raw" / "sources" / "02_进阶技巧" / "download_progress.json").write_text(
        "{}", encoding="utf-8")
    (tmp_path / "raw" / "sources" / "01_新手入门" / "notes.txt").write_text(
        "plain text", encoding="utf-8")
    return tmp_path


def _gap_file(root: Path) -> Path:
    return root / ".index" / "knowledge_gaps.json"


def _write_gaps(root: Path, raw_hints: list[str]) -> None:
    _gap_file(root).parent.mkdir(parents=True, exist_ok=True)
    gaps = [{
        "slug": f"gap-{i}",
        "raw_hint": h,
        "referenced_by": ["ref-page"],
        "created_at": 1,
        "status": "open",
    } for i, h in enumerate(raw_hints)]
    _gap_file(root).write_text(
        json.dumps({"version": 1, "gaps": gaps}, ensure_ascii=False),
        encoding="utf-8")


def _build(root: Path, **kw):
    sys_path = __import__("sys").path
    if str(REPO_ROOT) not in sys_path:
        sys_path.insert(0, str(REPO_ROOT))
    from scripts.plan_reingest_batches import build_plan
    return build_plan(root, **kw)


# ── batch partition ────────────────────────────────────────────────

def test_batches_are_at_most_20_files(mini_wiki: Path) -> None:
    for d, files in {
        "raw/sources/01_新手入门": [f"f{i:02d}.md" for i in range(25)],
        "raw/sources/02_进阶技巧": [f"g{i:02d}.md" for i in range(20)],
    }.items():
        p = mini_wiki / d
        p.mkdir(parents=True, exist_ok=True)
        for f in files:
            (p / f).write_text("# x\n内容", encoding="utf-8")
    plan = _build(mini_wiki)
    # 5 fixture md + 25 + 20 = 50 total
    assert plan["summary"]["raw_md_total"] == 50
    assert all(len(b["files"]) <= 20 for b in plan["batches"])
    # 50 files → 3 batches (20/20/10)
    assert [len(b["files"]) for b in plan["batches"]] == [20, 20, 10]


# ── extension whitelist ────────────────────────────────────────────

def test_non_md_files_excluded(mini_wiki: Path) -> None:
    plan = _build(mini_wiki)
    all_files = [f for b in plan["batches"] for f in b["files"]]
    assert all(f.endswith(".md") for f in all_files)
    assert not any("download_progress" in f for f in all_files)
    assert not any(f.endswith(".txt") for f in all_files)
    assert not any("download_progress" in f for b in plan["batches"] for f in b["files"])
    # Non-doc files are recorded in the skipped list (audit), never in batches.
    skipped = {s["path"] for s in plan["skipped"]}
    assert any("download_progress.json" in s for s in skipped)
    assert any(s.endswith(".txt") for s in skipped)
    assert plan["summary"]["raw_md_total"] == 5  # 3 + 2 md, json/txt excluded


# ── gap priority ───────────────────────────────────────────────────

def test_gap_raws_come_first(mini_wiki: Path) -> None:
    _write_gaps(mini_wiki, [
        # Absolute-ish hint (as stored by Phase 3 commit path)
        str(mini_wiki / "raw" / "sources" / "02_进阶技巧" / "戊进阶.md"),
        # Project-relative hint
        "raw/sources/01_新手入门/乙入门.md",
    ])
    plan = _build(mini_wiki)
    all_files = [f for b in plan["batches"] for f in b["files"]]
    gap_files = ["raw/sources/02_进阶技巧/戊进阶.md",
                 "raw/sources/01_新手入门/乙入门.md"]
    # Every gap-hit raw must appear before any non-gap raw.
    first_non_gap = next(
        (i for i, f in enumerate(all_files) if f not in gap_files), len(all_files))
    assert all(all_files.index(g) < first_non_gap for g in gap_files)
    assert plan["summary"]["gap_priority_raws"] == 2


def test_gap_hint_for_missing_raw_ignored(mini_wiki: Path) -> None:
    _write_gaps(mini_wiki, ["raw/sources/99_不存在/幽灵.md"])
    plan = _build(mini_wiki)
    assert plan["summary"]["gap_priority_raws"] == 0
    assert plan["summary"]["raw_md_total"] == 5


# ── theme progression ──────────────────────────────────────────────

def test_theme_directory_progression(mini_wiki: Path) -> None:
    plan = _build(mini_wiki)
    all_files = [f for b in plan["batches"] for f in b["files"]]
    # After gap files (none here), remaining sorted by dir then filename
    # (CJK code point order: 丙 < 乙 < 甲, 丁 < 戊).
    assert all_files == [
        "raw/sources/01_新手入门/丙入门.md",
        "raw/sources/01_新手入门/乙入门.md",
        "raw/sources/01_新手入门/甲入门.md",
        "raw/sources/02_进阶技巧/丁进阶.md",
        "raw/sources/02_进阶技巧/戊进阶.md",
    ]


# ── coverage / determinism ─────────────────────────────────────────

def test_plan_covers_every_raw_exactly_once(mini_wiki: Path) -> None:
    plan = _build(mini_wiki)
    all_files = [f for b in plan["batches"] for f in b["files"]]
    assert len(all_files) == len(set(all_files)) == plan["summary"]["raw_md_total"]
    for f in all_files:
        assert (mini_wiki / f).is_file()


def test_build_is_deterministic(mini_wiki: Path) -> None:
    a = json.dumps(_build(mini_wiki), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_build(mini_wiki), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_manifest_shape_consumable_by_executor(mini_wiki: Path) -> None:
    plan = _build(mini_wiki)
    assert "summary" in plan and "batches" in plan
    for b in plan["batches"]:
        assert set(b) >= {"theme", "batch_no", "files"}
        assert isinstance(b["batch_no"], int)
