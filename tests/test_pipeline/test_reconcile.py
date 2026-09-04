"""Phase 1.3 H6/O6 tests — 引用-产出对账（判定集合 + gap 采集）。"""
from __future__ import annotations

from pathlib import Path


from src.pipeline.reconcile import (
    collect_missing_slugs,
    make_missing_slugs_resolver,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def _make_paths(tmp_path: Path) -> WikiPaths:
    ensure_knowledge_base(tmp_path)
    return WikiPaths(tmp_path)


def _page(pid: str, *, relations=None, body: str = "") -> WikiPage:
    return WikiPage(id=pid, title=pid, type=PageType.CONCEPT,
                    relations=relations or [], body=body)


def _rel(target: str) -> "object":
    from src.wiki.core.types import Relation
    return Relation(target_id=target, type="references")


def test_missing_slugs_resolver_flags_ghost_reference(tmp_path):
    """resolver 对引用幽灵 slug 的产出返回缺失清单（H6 判定）。"""
    paths = _make_paths(tmp_path)
    resolver = make_missing_slugs_resolver(paths, produced_prefix={"source-abc"})
    pages = [
        {"id": "c1", "relations": [{"target": "现实概念"}], "slots": {"body": "见 [[幽灵概念]]"}},
        {"id": "source-abc", "relations": [], "slots": {}},
    ]
    missing = resolver(pages)
    # 本批未产出的引用（现实概念）与幽灵引用都算缺失
    assert "现实概念" in missing
    assert "幽灵概念" in missing
    # produced_prefix 可解析
    assert "source-abc" not in missing
    # c1 是本批产出 id，不判缺失
    assert "c1" not in missing


def test_missing_slugs_resolver_resolves_disk_page(tmp_path):
    """磁盘上已有页（含 CJK 顿号 id）被引用 → 不判缺失（B-H3 假断链消解）。"""
    paths = _make_paths(tmp_path)
    write_page(paths, _page("语言-、-动作-、-神态结合描写"))
    resolver = make_missing_slugs_resolver(paths)
    pages = [
        {"id": "c1", "relations": [{"target": "语言、动作、神态结合描写"}], "slots": {}},
    ]
    assert resolver(pages) == []  # 自然 wikilink 归一后与磁盘 id 一致


def test_missing_slugs_resolver_resolves_via_alias(tmp_path):
    """别名注册表可解析的 target 不判缺失（H6 并集、别名优先）。"""
    paths = _make_paths(tmp_path)
    from src.wiki.features.slug_aliases import SlugAliasRegistry
    reg = SlugAliasRegistry(tmp_path)
    reg.add("qi-dai-gan", "qi-dai-gan-chuangzuo")
    reg.save()
    resolver = make_missing_slugs_resolver(paths)
    pages = [{"id": "c1", "relations": [{"target": "qi-dai-gan"}], "slots": {}}]
    assert resolver(pages) == []


def test_collect_missing_slugs_references_and_provenance(tmp_path):
    """collect_missing_slugs 返回 (slug, 引用页 id) 供 gap 写入。"""
    paths = _make_paths(tmp_path)
    pages = [
        _page("p1", relations=[_rel("幽灵概念")]),
        _page("p2", body="见 [[另一个幽灵]]"),
    ]
    missing = collect_missing_slugs(pages, paths)
    by_slug = dict(missing)
    assert by_slug["幽灵概念"] == "p1"
    assert by_slug["另一个幽灵"] == "p2"


def test_missing_slugs_resolver_scans_list_slots(tmp_path):
    """槽值是 wikilink 数组（LLM 常见形态）时也要扫到幽灵引用。"""
    paths = _make_paths(tmp_path)
    resolver = make_missing_slugs_resolver(paths)
    pages = [{
        "id": "c1",
        "relations": [],
        "slots": {"related_concepts": ["[[现实概念]]", "[[幽灵A]]"], "references": "[[幽灵B]]"},
    }]
    missing = resolver(pages)
    assert "幽灵A" in missing
    assert "幽灵B" in missing
    assert "现实概念" in missing  # 未产出且不在磁盘，确实缺失
    assert "c1" not in missing    # 本批产出 id 可解析


def test_collect_missing_slugs_excludes_resolvable(tmp_path):
    """产出/磁盘/别名/索引内目标不记 gap。"""
    paths = _make_paths(tmp_path)
    write_page(paths, _page("现实概念"))
    pages = [
        _page("p1", relations=[_rel("现实概念"), _rel("幽灵")]),
        _page("p2", body="[[p1]]"),
    ]
    missing = [s for s, _ in collect_missing_slugs(pages, paths)]
    assert "现实概念" not in missing
    assert "p1" not in missing  # 本批产出
    assert missing == ["幽灵"]


def test_collect_missing_slugs_blocks_type_prefix_before_normalize(tmp_path):
    """类型前缀幻觉（source-补充教程）在归一剥前缀前被 blocklist 拦截。

    回归：若先归一后查 blocklist，source-补充教程 → 补充教程 会绕过
    `^(source|...)-` 正则（1.3 review Important-1）。
    """
    paths = _make_paths(tmp_path)
    pages = [
        _page("p1", relations=[_rel("source-补充教程"), _rel("正常概念")]),
    ]
    missing = [s for s, _ in collect_missing_slugs(pages, paths)]
    assert "补充教程" not in missing, "type-prefixed reference must be blocked pre-normalization"
    assert "source-补充教程" not in missing
    assert "正常概念" in missing


def test_collect_missing_slugs_blocks_legacy_exact_slugs(tmp_path):
    """既有 stub blocklist 精确 slug（feishu 等）继承进 gap 判定。"""
    paths = _make_paths(tmp_path)
    pages = [
        _page("p1", relations=[_rel("feishu"), _rel("真实缺口")]),
    ]
    missing = [s for s, _ in collect_missing_slugs(pages, paths)]
    assert "feishu" not in missing
    assert "真实缺口" in missing


def test_collect_missing_slugs_covers_extra_pages(tmp_path):
    """Phase 3 实测回归：反向边给存量页（extras）加的不存在 target 必须入 gap。

    generate_ingest 的 missing_slugs 采集在 _compute_reverse_relations 之后
    对 pages + extra_pages 一起执行——extras 页的反向 relation 可能引用
    不存在页（如 `玄幻小说` 被 extras 反向引用 `玄幻与仙侠区分对比`），
    若只 collect pages 则这些断链永远不入 gap 账本（M1 残留）。
    """
    paths = _make_paths(tmp_path)
    # 磁盘存量页（extras）：含指向不存在页的反向 relation
    write_page(paths, _page("存量页", relations=[_rel("幽灵反向目标")]))
    # 本批新页引用存量页 → extras 会加载并合并反向边
    pages = [
        _page("新页", relations=[_rel("存量页")]),
    ]
    # 模拟 reverse 之后的最终集合：pages + extras 都进 collect
    from src.wiki.storage.page_writer import read_page
    extra_page = read_page(paths.wiki_concepts / "存量页.md")
    missing = [s for s, _ in collect_missing_slugs(
        pages + [extra_page], paths,
        produced_slugs={p.id for p in pages} | {p.id for p in [extra_page]},
    )]
    assert "幽灵反向目标" in missing, (
        f"extras 页的反向断链必须入 gap，got: {missing}"
    )
    assert "存量页" not in missing  # 磁盘页本身可解析
