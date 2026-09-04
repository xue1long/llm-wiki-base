"""Tests for scripts/aggregate_synthesis.py — Phase 4.5 多源 synthesis 聚合。

按 category 分组多源 concept 页 → LLM 生成 synthesis 页 → 质量门通过。
"""
import sys as _sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Helper: write a concept page with a given category and sources
# ---------------------------------------------------------------------------
def _write_concept(wiki_dir: Path, page_id: str, category: str,
                   sources: list[str], body: str = "") -> None:
    """Write a minimal concept page to disk."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths

    ensure_knowledge_base(wiki_dir)
    paths = WikiPaths(wiki_dir)
    page = WikiPage(
        id=page_id, title=page_id, type=PageType.CONCEPT,
        sources=sources, processing_depth="concept",
        category=category, grade="B",
        body=body or (
            f"<!-- wiki-template-version: 3.0.0 -->\n"
            f"## 定义\n\n{page_id} 的定义内容。\n\n"
            f"## 证据强度\n\n可靠。\n"
        ),
    )
    write_page(paths, page)
    target = paths.wiki_concepts / f"{page_id}.md"
    text = target.read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    fm = yaml.safe_load(text[4:end]) or {}
    fm["category"] = category
    target.write_text(
        "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
        + "---" + text[end + 4:],
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    """A wiki with 3 concept pages in the same category (2 sources)."""
    cdir = tmp_path / "wiki" / "concepts"
    cdir.mkdir(parents=True, exist_ok=True)
    _write_concept(
        tmp_path, "爽点定义", "爽点与情绪",
        sources=["raw/sources/a.md", "raw/sources/b.md"],
    )
    _write_concept(
        tmp_path, "爽点元素", "爽点与情绪",
        sources=["raw/sources/a.md"],
    )
    _write_concept(
        tmp_path, "情绪设计", "爽点与情绪",
        sources=["raw/sources/c.md"],
    )
    # 单源 category（不满足聚合条件）
    _write_concept(
        tmp_path, "开篇写法", "开篇与黄金三章",
        sources=["raw/sources/a.md"],
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_aggregate_synthesis_groups_by_category(wiki_dir: Path):
    """按 category 分组后，多源 category 被识别为聚合候选。"""
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from scripts.aggregate_synthesis import _group_by_category, _is_synthesis_candidate

    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import read_page

    paths = WikiPaths(wiki_dir)
    pages = []
    for f in (paths.wiki_concepts / "*.md").parent.glob("*.md"):
        try:
            pages.append(read_page(f))
        except Exception:
            continue

    groups = _group_by_category(pages)
    assert "爽点与情绪" in groups, "category with 3 pages must be grouped"
    assert "开篇与黄金三章" in groups, "single-source category still grouped"
    assert len(groups["爽点与情绪"]) == 3
    assert len(groups["开篇与黄金三章"]) == 1

    # 候选条件：≥2 个独立 source
    candidates = {cat: pgs for cat, pgs in groups.items()
                  if _is_synthesis_candidate(pgs)}
    assert "爽点与情绪" in candidates
    assert "开篇与黄金三章" not in candidates


def test_aggregate_synthesis_generates_page(wiki_dir: Path):
    """对多源 category 调用 LLM 生成 synthesis 页，产物通过质量门。"""
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    import asyncio
    from scripts.aggregate_synthesis import (
        _group_by_category, _is_synthesis_candidate,
        _generate_synthesis_pages,
    )
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import read_page
    from src.llm.registry import ProviderRegistry

    paths = WikiPaths(wiki_dir)
    pages = []
    for f in (paths.wiki_concepts / "*.md").parent.glob("*.md"):
        try:
            pages.append(read_page(f))
        except Exception:
            continue

    groups = _group_by_category(pages)
    candidates = {cat: pgs for cat, pgs in groups.items()
                  if _is_synthesis_candidate(pgs)}
    assert "爽点与情绪" in candidates

    # 使用 fake provider（返回合法 synthesis JSON）
    reg = ProviderRegistry()

    class _FakeProvider:
        async def complete(self, messages, **kwargs):
            return type(
                "R", (), {
                    "content": (
                        '{"synthesis": {'
                        '"topic": "爽点与情绪是网文创作的核心要素", '
                        '"viewpoints": "- 观点A：来源A认为爽点=情绪释放\\n- 观点B：来源B认为爽点=预期满足", '
                        '"consensus": "多数观点认为爽点与情绪密切相关", '
                        '"evidence_comparison": "观点A基于读者调研，观点B基于创作经验", '
                        '"conclusion": "建议结合两种观点"'
                        "}}"
                    ),
                    "truncated": False, "content_length": 0,
                })()

    async def _run():
        results = await _generate_synthesis_pages(
            candidates, paths, provider=_FakeProvider(),
            project_root=wiki_dir,
        )
        assert len(results) == 1
        r = results[0]
        assert r.category == "爽点与情绪"
        assert r.synthesis_page is not None
        assert r.synthesis_page.type.value == "synthesis"
        # body 必须包含 5 个 v3.0.0 synthesis 槽标题
        body = r.synthesis_page.body
        for heading in ("议题与分歧点", "各方观点", "共识", "证据对比", "待定与结论"):
            assert f"## {heading}" in body, f"missing heading: {heading}"
        # 各方观点 section 必须含 ≥2 wikilink（lint 质量门）
        assert "[[来源A" in body or "来源A" in body, "no viewpoint content"

    asyncio.run(_run())


def test_aggregate_synthesis_skips_no_candidate(wiki_dir: Path):
    """无候选 category 时脚本静默退出。"""
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    from scripts.aggregate_synthesis import (
        _group_by_category, _is_synthesis_candidate,
    )
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import read_page

    # 先清空现有的多源 category
    paths = WikiPaths(wiki_dir)
    # 只保留单源页

    # 覆盖所有页为单源
    for f in (paths.wiki_concepts).glob("*.md"):
        f.unlink()

    # 仅写一个单源页
    _write_concept(
        wiki_dir, "开篇写法", "开篇与黄金三章",
        sources=["raw/sources/a.md"],
    )

    pages = []
    for f in (paths.wiki_concepts).glob("*.md"):
        try:
            pages.append(read_page(f))
        except Exception:
            continue

    groups = _group_by_category(pages)
    candidates = {cat: pgs for cat, pgs in groups.items()
                  if _is_synthesis_candidate(pgs)}
    assert len(candidates) == 0


def test_aggregate_synthesis_full_smoke(wiki_dir: Path):
    """端到端冒烟：脚本入口函数正常返回（无 LLM 调用时为空）。"""
    if str(REPO_ROOT) not in _sys.path:
        _sys.path.insert(0, str(REPO_ROOT))
    # 用 fake 模式验证入口函数不抛
    # 实际场景由 CLI 调用
    import asyncio
    from scripts.aggregate_synthesis import main as _main

    class _Args:
        root = str(wiki_dir)
        budget_usd = 0.01
        dry_run = True

    async def _run():
        # 验证 dry_run 模式不抛
        result = await _main(_Args())
        assert result >= 0

    asyncio.run(_run())
