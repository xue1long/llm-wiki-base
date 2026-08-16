"""Unit tests for src/wiki/features/metrics.py (spec §6 M1/M2/M4/M6/M7 core).

Phase 0.1 — created with the metrics core; Phase 1.8 extends the batch-set
mode. These tests exercise the shared measurement core against a minimal
tmp wiki so baseline / gate / final acceptance never drift apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.wiki.core.paths import WikiPaths
from src.wiki.features.lint import LintIssue, LintReport, LintSeverity
from src.wiki.features.metrics import (
    body_has_placeholder,
    census_wiki,
    collect_wikilinks,
    metric_broken_links,
    metric_deep_reference_rate,
    metric_slot_compliance,
    metric_source_fulltext_pollution,
    metric_synthesis_count,
    read_page_snapshots,
)

FM = """---
id: {sid}
title: {title}
type: {ptype}
sources:
- {src}
relations:
- target: {rel_target}
  type: references
  weight: 0.8
---
"""


def _write_page(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def mini_wiki(tmp_path: Path) -> WikiPaths:
    """Minimal wiki: 1 raw file, 1 source page, 2 concepts, 1 synthesis."""
    raw_dir = tmp_path / "raw" / "sources"
    raw_dir.mkdir(parents=True)
    (raw_dir / "a.md").write_text("raw A content", encoding="utf-8")
    (raw_dir / "b.md").write_text("raw B content", encoding="utf-8")
    (raw_dir / "c.md").write_text("raw C content", encoding="utf-8")

    _write_page(tmp_path, "wiki/sources/s-a.md", FM.format(
        sid="s-a", title="SrcA", ptype="source", src="raw\\sources\\a.md",
        rel_target="c1",
    ))
    _write_page(tmp_path, "wiki/concepts/c1.md", FM.format(
        sid="c1", title="Concept1", ptype="concept", src="raw/sources/a.md",
        rel_target="c2",
    ) + "## 定义\n\n[[s-a]]\n")
    # self-produced page for raw B (sources == [B] only) → NOT a deep ref
    _write_page(tmp_path, "wiki/concepts/c2.md", FM.format(
        sid="c2", title="Concept2", ptype="concept", src="raw/sources/b.md",
        rel_target="",
    ) + "## 定义\n\nB body\n")
    # single-source entity page (sources == [A] only) → NOT a deep ref
    _write_page(tmp_path, "wiki/entities/e1.md",
                "---\nid: e1\ntitle: Ent1\ntype: entity\nsources:\n- raw/sources/a.md\n---\n\n## 简介\n\n[[c1]]\n")
    # synthesis page (aggregation) → deep ref for A + C
    _write_page(tmp_path, "wiki/synthesis/syn1.md",
                "---\nid: syn1\ntitle: Syn1\ntype: synthesis\nsources:\n- raw/sources/a.md\n- raw/sources/c.md\n---\n\n## 议题\n\n## 各方观点\n\n- [[c1]]\n- [[c2]]\n")
    return WikiPaths(tmp_path)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def test_read_page_snapshots_fields(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    by_id = {s.id: s for s in snaps}
    assert "s-a" in by_id
    s = by_id["s-a"]
    assert s.page_type == "source"
    # backslash raw path is normalized by the snapshot reader as-is (caller
    # normalizes for matching); at minimum it must not crash and must carry
    # one source entry.
    assert len(s.sources) == 1
    assert "a.md" in s.sources[0]
    # relations parsed with target
    assert any(r.get("target") == "c1" for r in s.relations)


def test_collect_wikilinks(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    s = next(x for x in snaps if x.id == "c1")
    links = collect_wikilinks(s)
    assert "c2" in links  # from relations target
    assert "s-a" in links  # from body [[s-a]]


# ---------------------------------------------------------------------------
# M1 broken links
# ---------------------------------------------------------------------------

def test_metric_broken_links_basic(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    known = {s.id for s in snaps}
    report = metric_broken_links(snaps, known)
    # c2's body has no links; syn1 links c1/c2 (known); all known → 0 broken
    assert report.broken_links == 0
    assert report.total_links > 0


def test_metric_broken_links_with_alias(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    known = {s.id for s in snaps}
    # add a ghost link: rewrite e1's body to point at a variant slug
    e1 = next(s for s in snaps if s.id == "e1")
    e1.body = e1.body + "\n[[qi-dai-gan]]\n"
    report = metric_broken_links(snaps, known)
    assert "qi-dai-gan" in report.broken_slugs
    assert report.broken_links == 1
    # alias registry resolves it → not broken
    alias = {"qi-dai-gan": "c1"}
    report2 = metric_broken_links(snaps, known, alias_canonical=alias.get)
    assert report2.broken_links == 0


def test_metric_broken_links_rate(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    snaps[0].body += "\n[[ghost-slug]]\n"
    known = {s.id for s in snaps}
    report = metric_broken_links(snaps, known)
    assert report.total_links > 0
    assert 0.0 < report.rate < 1.0


def test_metric_broken_links_normalizes_slug_variants(mini_wiki: WikiPaths) -> None:
    """Phase 3 实测回归：M1 判定必须归一 slug 变体（plan 1.3 统一归一语义）。

    novel-wiki 首批实测暴露：页面引用 ``[[老作者补贴体系--华夏天空]]``（双横线）
    而磁盘页 id 是 ``老作者补贴体系-华夏天空``（单横线）——精确匹配判为断链，
    实为同一 slug 的连字符变体（假断链）。归一后应判为可解析。
    """
    from src.wiki.features.slug_utils import normalize_reconcile_slug

    snaps = census_wiki(mini_wiki)
    # 用真实中文带连字符 slug：磁盘页 id 单横线，引用双横线变体
    disk_id = "老作者补贴体系-华夏天空"
    variant = "老作者补贴体系--华夏天空"
    known = {s.id for s in snaps} | {disk_id}
    snaps[0].body += f"\n[[{variant}]]\n"

    # 未归一：判为断链
    report = metric_broken_links(snaps, known)
    assert variant in report.broken_slugs

    # 归一 known 集合后：可解析
    known_norm = {normalize_reconcile_slug(s) for s in known}
    report2 = metric_broken_links(snaps, known, known_norm=known_norm)
    assert variant not in report2.broken_slugs, (
        f"双横线变体应归一解析，got: {report2.broken_slugs}"
    )
    # 真实不存在断链仍被捕获
    snaps[0].body += "\n[[真不存在的幽灵页]]\n"
    report3 = metric_broken_links(snaps, known, known_norm=known_norm)
    assert "真不存在的幽灵页" in report3.broken_slugs


# ---------------------------------------------------------------------------
# M2 deep reference rate
# ---------------------------------------------------------------------------

def test_metric_deep_reference_rate(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    raw_files = list((mini_wiki.root / "raw" / "sources").glob("*.md"))
    rate, referenced, total = metric_deep_reference_rate(
        snaps, raw_files, project_root=mini_wiki.root
    )
    assert total == 3
    # a: via syn1 (synthesis) + e1? e1 is single-source (not deep); a also
    # deep via c1 body [[s-a]] (wikilink → source page rule)
    # c: via syn1 → deep
    # b: only self-produced c2 → NOT deep
    # Expect a + c = 2/3.
    assert referenced == 2
    assert rate == pytest.approx(2 / 3)


def test_metric_deep_reference_wikilink_to_source(mini_wiki: WikiPaths) -> None:
    """Concept page linking its own source page counts as deep ref (0.2 rule)."""
    snaps = census_wiki(mini_wiki)
    raw_files = list((mini_wiki.root / "raw" / "sources").glob("*.md"))
    # c2 (self-produced for b) gains a wikilink to source page s-a → b's
    # source is a, so a stays; add a link to source page for b? There is no
    # source page for b. Instead: c2 body already has "B body"; add a
    # wikilink [[s-a]] so a is referenced by c2 as well (still deep via syn1).
    c2 = next(s for s in snaps if s.id == "c2")
    c2.body += "\n[[s-a]]\n"
    rate, referenced, total = metric_deep_reference_rate(
        snaps, raw_files, project_root=mini_wiki.root
    )
    # a now via syn1 + c2's wikilink; c via syn1; b still not deep.
    assert referenced == 2


def test_metric_deep_reference_rate_empty(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    rate, ref, total = metric_deep_reference_rate(snaps, [], project_root=mini_wiki.root)
    assert (rate, ref, total) == (0.0, 0, 0)


# ---------------------------------------------------------------------------
# M4 / M6 / M7
# ---------------------------------------------------------------------------

def test_metric_slot_compliance_counts() -> None:
    report = LintReport(
        project_id="p",
        issues=[
            LintIssue("LINT-MISSING-SECTION", LintSeverity.ERROR, "m1", "x"),
            LintIssue("LINT-MISSING-SECTION", LintSeverity.ERROR, "m2", "x"),
            LintIssue("LINT-PLACEHOLDER", LintSeverity.ERROR, "p1", "x"),
            LintIssue("LINT-RAW-PASTE", LintSeverity.ERROR, "r1", "x"),
        ],
    )
    missing, placeholder, other = metric_slot_compliance(report)
    assert missing == 2
    assert placeholder == 1
    assert other == 1


def test_body_has_placeholder() -> None:
    assert body_has_placeholder("见下游概念页")
    assert body_has_placeholder("（系统占位：此项由系统补齐）")
    assert not body_has_placeholder("一段正常内容")


def test_metric_synthesis_count(mini_wiki: WikiPaths) -> None:
    assert metric_synthesis_count(mini_wiki) == 1


def test_metric_source_fulltext_pollution(mini_wiki: WikiPaths) -> None:
    snaps = census_wiki(mini_wiki)
    assert metric_source_fulltext_pollution(snaps) == 0
    s = next(x for x in snaps if x.id == "s-a")
    s.body += "\n## 正文内容\n\n全文\n"
    assert metric_source_fulltext_pollution(snaps) == 1
