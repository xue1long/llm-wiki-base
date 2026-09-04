"""计划 2026-08-18 Task 4 — scripts/cleanup_invalid_tags.py 改用公共 normalize_tags。

- dry-run：输出 mapping / removal / mandatory 清单，不写盘
- --apply：写盘（legacy 前缀映射 + 非法删除 + 按兼容政策策略 1 补 mandatory）
- --page-ids：只处理指定页面
- 干净页面零改动
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.cleanup_invalid_tags as cleanup_mod  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.storage.ensure import ensure_knowledge_base  # noqa: E402
from src.wiki.storage.page_writer import read_page  # noqa: E402


def _write_page_raw(paths: WikiPaths, page_id: str, tags: list[str],
                    subdir: str = "concepts") -> Path:
    """直接写带非法 tags 的页面文件（绕过 write_page 的写前校验）。"""
    d = getattr(paths, f"wiki_{subdir}")
    d.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": page_id,
        "title": page_id,
        "type": "concept" if subdir == "concepts" else "source",
        "sources": ["raw/sources/a.md"],
        "grade": "B",
        "tags": tags,
    }
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False)
    p = d / f"{page_id}.md"
    p.write_text(f"---\n{fm_text}---\n\n## 定义\n\n内容。\n", encoding="utf-8")
    return p


def _run(monkeypatch, root: Path, *args: str) -> int:
    monkeypatch.setattr(
        sys, "argv",
        ["cleanup_invalid_tags.py", "--root", str(root), *args],
    )
    return cleanup_mod.main()


def test_dry_run_reports_mapping_and_does_not_write(tmp_path, monkeypatch, capsys):
    root = tmp_path / "wiki"
    ensure_knowledge_base(root)
    paths = WikiPaths(root)
    _write_page_raw(paths, "p1", ["func/教程", "genre/玄幻"])

    rc = _run(monkeypatch, root, "--page-ids", "p1")
    assert rc == 0
    out = capsys.readouterr().out
    assert "map func/教程 -> 功能/教程" in out
    assert "map genre/玄幻 -> 题材/玄幻" in out
    assert "add mandatory 素材/ugc" in out
    assert "add mandatory 可信度/ugc" in out
    assert "dry-run" in out
    # 未写盘
    on_disk = read_page(paths.wiki_concepts / "p1.md")
    assert on_disk.tags == ["func/教程", "genre/玄幻"]


def test_apply_writes_normalized_tags(tmp_path, monkeypatch):
    root = tmp_path / "wiki"
    ensure_knowledge_base(root)
    paths = WikiPaths(root)
    _write_page_raw(paths, "p2", ["func/教程", "genre/玄幻", "whatever/x"])

    rc = _run(monkeypatch, root, "--page-ids", "p2", "--apply")
    assert rc == 0
    on_disk = read_page(paths.wiki_concepts / "p2.md")
    assert on_disk.tags == ["功能/教程", "题材/玄幻", "素材/ugc", "可信度/ugc"], (
        f"legacy mapped + invalid removed + mandatory added, got: {on_disk.tags}"
    )


def test_apply_removes_unmappable_tags(tmp_path, monkeypatch):
    """batch 8 失败案例：func/结构、genre/平台 值域非法且无法安全映射 → 删除。"""
    root = tmp_path / "wiki"
    ensure_knowledge_base(root)
    paths = WikiPaths(root)
    _write_page_raw(paths, "p3", ["func/结构", "genre/平台", "功能/教程"])

    rc = _run(monkeypatch, root, "--page-ids", "p3", "--apply")
    assert rc == 0
    on_disk = read_page(paths.wiki_concepts / "p3.md")
    assert on_disk.tags == ["功能/教程", "素材/ugc", "可信度/ugc"], (
        f"unmappable removed, valid kept + mandatory, got: {on_disk.tags}"
    )


def test_clean_page_untouched_and_page_ids_filters(tmp_path, monkeypatch):
    root = tmp_path / "wiki"
    ensure_knowledge_base(root)
    paths = WikiPaths(root)
    _write_page_raw(paths, "clean", ["题材/玄幻", "素材/ugc", "可信度/ugc"])
    _write_page_raw(paths, "dirty", ["func/教程"])

    rc = _run(monkeypatch, root, "--page-ids", "clean")
    assert rc == 0
    # 未在 --page-ids 中的页面不受影响
    assert read_page(paths.wiki_concepts / "dirty.md").tags == ["func/教程"]
    # 干净页面零改动（mapped/removed/mandatory 全空 → 跳过）
    assert read_page(paths.wiki_concepts / "clean.md").tags == [
        "题材/玄幻", "素材/ugc", "可信度/ugc",
    ]
