"""Phase 1 (2026-08-01 NDG plan): run_ingest split into generate_ingest /
commit_ingest.

Locks in the three invariants of the split:
  1. ``generate_ingest`` performs ZERO disk writes (the quality gate can run
     before anything hits the wiki).
  2. ``commit_ingest`` performs the write half (pages + index + log) for both
     ``pages`` and ``extra_pages`` (pre-existing pages that gained inverse
     edges).
  3. ``run_ingest`` is a thin wrapper = ``generate_ingest`` + ``commit_ingest``
     and returns the same page set as the pre-split behaviour.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from src.pipeline.ingest import (
    commit_ingest,
    generate_ingest,
    run_ingest,
)
from tests.support.test_helpers import ScriptedLLMProvider
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.relations import Relation
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import read_page, write_page


@pytest.fixture(autouse=True)
def _legacy_pipeline_mode(monkeypatch):
    """These tests were written for the legacy pipeline path.
    Force legacy mode so they don't enter the candidate path."""
    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "legacy")


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Return {relative_posix_path: content} for every file under *root*."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8")
    return out


def _page_sig(pages: list[WikiPage]) -> set[tuple]:
    """A stable signature of the page set: (id, type, title, grade)."""
    return {(p.id, p.type.value, p.title, p.grade) for p in pages}


# A unified-path LLM script that produces one concept page + a dangling
# [[其他]] reference (which Fix E turns into a stub). Used by several tests.
_CONCEPT_SCRIPT = [
    {
        "pages": [
            {
                "id": "c1",
                "type": "concept",
                "title": "概念一",
                "slots": {
                    "definition": "这是一个用于测试的概念定义，内容足够长。",
                    "characteristics": ["特征一", "特征二"],
                    "examples": ["示例一"],
                    "related_concepts": ["[[其他]]"],
                    "references": ["[[其他]]"],
                },
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Invariant 1: generate_ingest must not touch disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_ingest_makes_no_disk_writes(tmp_path: Path) -> None:
    """generate_ingest returns pages/meta but leaves the whole project tree
    byte-for-byte unchanged (no write_page / append_to_index / log_event)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "gen-no-write.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("这是一段用于测试的源文档内容。", encoding="utf-8")

    provider = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])

    before = _snapshot_tree(tmp_path)

    pages, extra_pages, meta = await generate_ingest(
        paths=paths,
        source_path=raw,
        source_text="这是一段用于测试的源文档内容。",
        provider=provider,
        task_id="kb-gen-no-write",
    )

    after = _snapshot_tree(tmp_path)

    assert before == after, (
        "generate_ingest must not write anything under the project; "
        f"differs at keys: {sorted(set(before) ^ set(after))}"
    )
    # In-memory results are still produced and complete.
    assert pages, "generate_ingest must produce pages in memory"
    assert any(p.type == PageType.SOURCE for p in pages), (
        "the source page must be constructed inside generate_ingest (Fix D)"
    )
    assert isinstance(extra_pages, list)
    assert isinstance(meta, dict)
    for key in (
        "analysis",
        "source_slug",
        "source_page_id",
        "source_grade",
        "downstream_count",
        "extra_pages_count",
        "rejected",
        "warnings",
    ):
        assert key in meta, f"meta must expose {key!r} for the gate"


# ---------------------------------------------------------------------------
# Invariant 2: commit_ingest performs the write half
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_ingest_writes_pages_index_and_log(tmp_path: Path) -> None:
    """commit_ingest writes every page file, appends to index.md and logs an
    ingest event."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "commit-me.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    pages = [
        WikiPage(
            id="src-commit-1234abcd",
            title="commit-me",
            type=PageType.SOURCE,
            sources=["raw/sources/commit-me.md"],
            body="## 摘要\n\n这是摘要内容。",
            grade="A",
            created_at=now,
            updated_at=now,
        ),
        WikiPage(
            id="概念一",
            title="概念一",
            type=PageType.CONCEPT,
            sources=["raw/sources/commit-me.md"],
            body="## 定义\n\n这是概念的定义内容，长度足够。",
            grade="B",
            created_at=now,
            updated_at=now,
        ),
    ]
    extra_pages = [
        WikiPage(
            id="old-target",
            title="旧目标",
            type=PageType.ENTITY,
            sources=[],
            body="旧页面。",
            grade="C",
            created_at=now,
            updated_at=now,
            relations=[Relation(target_id="src-commit-1234abcd", type="referenced_by")],
        ),
    ]

    await commit_ingest(
        paths=paths,
        source_path=raw,
        pages=pages,
        extra_pages=extra_pages,
        task_id="kb-commit",
    )
    # Page files on disk (both pages and extra_pages).
    assert (paths.wiki_sources / "src-commit-1234abcd.md").exists()
    assert (paths.wiki_concepts / "概念一.md").exists()
    assert (paths.wiki_entities / "old-target.md").exists()
    # Index catalog. extra_pages are pre-existing pages (already indexed);
    # only `pages` created this run are appended — matches the pre-split
    # run_ingest behaviour.
    index_text = paths.llm_wiki_index.read_text(encoding="utf-8")
    assert "src-commit-1234abcd" in index_text
    assert "概念一" in index_text
    assert "old-target" not in index_text
    # Audit log.
    log_text = paths.llm_wiki_log.read_text(encoding="utf-8")
    assert "ingest" in log_text
    assert "kb-commit" in log_text


# ---------------------------------------------------------------------------
# Invariant 3: run_ingest = generate_ingest + commit_ingest (same page set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ingest_equals_generate_plus_commit(tmp_path: Path) -> None:
    """run_ingest returns the exact same page set as generate+commit on the
    same inputs (source path, source text, LLM script) — the split is
    behaviour-preserving."""
    root_a = tmp_path / "proj-a"
    root_b = tmp_path / "proj-b"
    ensure_knowledge_base(root_a)
    ensure_knowledge_base(root_b)
    paths_a = WikiPaths(root_a)
    paths_b = WikiPaths(root_b)

    # Same absolute source path (outside both project roots → same slug hash
    # and same `sources` normalisation for both runs).
    raw = tmp_path / "shared-doc.md"
    raw.write_text("这是一段用于测试的共享源文档内容，包含足够的中文字符以通过预过滤器检查。" * 3, encoding="utf-8")

    source_text = "这是一段用于测试的共享源文档内容，包含足够的中文字符以通过预过滤器检查。" * 3

    # Via run_ingest (project A).
    provider_a = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])
    pages_run = await run_ingest(
        paths=paths_a,
        source_path=raw,
        source_text=source_text,
        provider=provider_a,
        task_id="kb-run",
    )

    # Via generate_ingest + commit_ingest (project B).
    provider_b = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])
    pages_gen, extra_gen, _meta = await generate_ingest(
        paths=paths_b,
        source_path=raw,
        source_text=source_text,
        provider=provider_b,
        task_id="kb-run",
    )
    await commit_ingest(
        paths=paths_b,
        source_path=raw,
        pages=pages_gen,
        extra_pages=extra_gen,
        task_id="kb-run",
    )

    # commit_ingest is now write-only (returns None); the page set it writes
    # is exactly the pages generate_ingest produced, so compare against that.
    assert _page_sig(pages_run) == _page_sig(pages_gen), (
        "run_ingest and generate+commit must produce identical page sets"
    )
    assert len(pages_run) == len(pages_gen)


# ---------------------------------------------------------------------------
# extra_pages: pre-existing targets referenced by new pages (read-only in
# generate, written only by commit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_extra_pages_without_writing_them(tmp_path: Path) -> None:
    """When a new page references a pre-existing page, generate_ingest loads
    it, adds the inverse edge in memory and returns it in extra_pages — but
    must NOT write the updated inverse edge to disk. commit_ingest does."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "extra-src.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    # Pre-existing entity on disk (no inverse edge yet).
    write_page(
        paths,
        WikiPage(
            id="old-target",
            title="旧目标",
            type=PageType.ENTITY,
            sources=[],
            body="旧页面。",
            grade="C",
            created_at=now,
            updated_at=now,
            relations=[],
        ),
    )

    provider = ScriptedLLMProvider(
        [
            {
                "pages": [
                    {
                        "id": "s1",
                        "type": "source",
                        "title": "extra-src",
                        "slots": {
                            "source_meta": "来源: 测试",
                            "summary": "摘要内容",
                            "key_points": ["要点一"],
                            "extracted_concepts": ["[[old-target]]"],
                        },
                        "relations": [{"target": "old-target", "type": "references"}],
                    },
                ],
            },
        ],
    )

    pages, extra_pages, meta = await generate_ingest(
        paths=paths,
        source_path=raw,
        source_text="内容",
        provider=provider,
        task_id="kb-extra",
    )

    # The source page was produced; the pre-existing entity came back in
    # extra_pages with the inverse edge in memory.
    assert any(p.type == PageType.SOURCE for p in pages)
    old = next((p for p in extra_pages if p.id == "old-target"), None)
    assert old is not None, "pre-existing target must be returned in extra_pages"
    assert any(r.target_id == pages[0].id and r.type == "referenced_by" for r in old.relations)

    # generate_ingest must NOT have written the inverse edge to disk yet.
    from src.wiki.storage.page_writer import read_page

    on_disk = read_page(paths.wiki_entities / "old-target.md")
    assert not on_disk.relations, (
        "generate_ingest must not persist inverse edges; commit_ingest does"
    )

    # commit_ingest persists the merged page.
    await commit_ingest(
        paths=paths,
        source_path=raw,
        pages=pages,
        extra_pages=extra_pages,
        task_id="kb-extra",
    )
    on_disk_after = read_page(paths.wiki_entities / "old-target.md")
    assert any(r.type == "referenced_by" for r in on_disk_after.relations)


# ---------------------------------------------------------------------------
# Phase 1.3 — 引用-产出对账 → gap 账本（H6/O6/H9：废除自动建 stub）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ingest_records_gap_for_ghost_reference(tmp_path: Path) -> None:
    """生成的页面引用幽灵 slug → run_ingest 后 gap 账本记录（含 raw_hint），
    且不再自动创建 stub 页（H9）。"""
    import json

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "ghost-ref.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("这是一篇引用不存在概念的文章。", encoding="utf-8")

    provider = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])

    await run_ingest(
        paths=paths,
        source_path=raw,
        source_text="这是一篇引用不存在概念的文章。",
        provider=provider,
        task_id="kb-ghost",
    )

    # gap 账本记录了幽灵引用（[[其他]]）
    gap_file = tmp_path / ".index" / "knowledge_gaps.json"
    assert gap_file.exists(), "gap ledger must be written by run_ingest"
    data = json.loads(gap_file.read_text(encoding="utf-8"))
    slugs = {g["slug"] for g in data["gaps"]}
    assert "其他" in slugs
    entry = next(g for g in data["gaps"] if g["slug"] == "其他")
    assert entry["status"] == "open"
    assert entry["raw_hint"] == "raw/sources/ghost-ref.md"
    assert entry["referenced_by"], "gap must record the referencing page id"

    # 不再自动创建 stub 页
    stubs = list((tmp_path / "wiki" / "_stubs").glob("*.md")) if (tmp_path / "wiki" / "_stubs").exists() else []
    assert stubs == [], "auto-stub creation must be removed (H9)"


@pytest.mark.asyncio
async def test_run_ingest_same_raw_twice_no_duplicate_gap(tmp_path: Path) -> None:
    """同一 raw 连跑两次：gap 账本不重复新增（dedup + referenced_by 累积）。"""
    import json

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "twice.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("第二次摄取相同的文档。", encoding="utf-8")

    provider = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])

    await run_ingest(paths=paths, source_path=raw,
                     source_text="第二次摄取相同的文档。", provider=provider,
                     task_id="kb-twice-1")
    await run_ingest(paths=paths, source_path=raw,
                     source_text="第二次摄取相同的文档。", provider=provider,
                     task_id="kb-twice-2")

    gap_file = tmp_path / ".index" / "knowledge_gaps.json"
    data = json.loads(gap_file.read_text(encoding="utf-8"))
    count = sum(1 for g in data["gaps"] if g["slug"] == "其他")
    assert count == 1, "same raw re-ingest must not duplicate gap entries"


@pytest.mark.asyncio
async def test_run_ingest_blocklist_slug_not_in_gap(tmp_path: Path) -> None:
    """blocklist slug（类型前缀 source-xxx / 平台名 feishu）不进 gap 账本。

    校验点：原始引用在归一剥前缀前被 blocklist 拦截——否则 source-补充教程
    会归一成补充教程绕过 `^(source|...)-` 正则（1.3 review Important-1）。
    """
    import json

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "blocked.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    blocked_script = [{
        "pages": [{
            "id": "c1", "type": "concept", "title": "概念",
            "slots": {"definition": "定义内容足够长。", "characteristics": ["c"],
                      "examples": ["e"], "related_concepts": ["[[source-补充教程]]"],
                      "references": ["[[feishu]]"]},
        }],
    }]
    provider = ScriptedLLMProvider(blocked_script)

    await run_ingest(paths=paths, source_path=raw, source_text="内容",
                     provider=provider, task_id="kb-blocked")

    gap_file = tmp_path / ".index" / "knowledge_gaps.json"
    # 全部引用被 blocklist 拦截 → 账本文件不存在或为空（无 gap 可记）
    if gap_file.exists():
        data = json.loads(gap_file.read_text(encoding="utf-8"))
        slugs = {g["slug"] for g in data["gaps"]}
    else:
        slugs = set()
    assert "补充教程" not in slugs, (
        "type-prefixed source-补充教程 must be blocked BEFORE normalization "
        "strips the prefix (1.3 review Important)"
    )
    assert "source-补充教程" not in slugs
    assert "feishu" not in slugs, "legacy exact-match stub blocklist must carry into gaps"


# ---------------------------------------------------------------------------
# Phase 3 实测发现：commit_ingest 必须接受 event 参数（extras 独立提交）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_ingest_accepts_event_kwarg(tmp_path: Path) -> None:
    """Phase 4 extras 提交以 ``event="reverse-relation"`` 调用 commit_ingest。

    Phase 3 首批实测暴露：phase4_batch._commit_all 的 extras 分支传了
    ``event=`` 关键字，但 commit_ingest 签名从未支持它 → 反向关系页提交
    必然失败（POSTCHECK exit 3）。本测试锁定 event 参数被接受并透传给
    log_event（audit 日志出现 reverse-relation 事件）。
    """
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "event-arg.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    pages = [
        WikiPage(
            id="src-event",
            title="event-arg",
            type=PageType.SOURCE,
            sources=["raw/sources/event-arg.md"],
            body="## 摘要\n\n摘要内容。",
            grade="A",
            created_at=now,
            updated_at=now,
        ),
    ]
    extras = [
        WikiPage(
            id="old-extra",
            title="旧页",
            type=PageType.CONCEPT,
            sources=[],
            body="旧页面。",
            grade="C",
            created_at=now,
            updated_at=now,
        ),
    ]

    await commit_ingest(
        paths=paths,
        source_path=raw,
        pages=pages,
        extra_pages=extras,
        task_id="kb-event",
        event="reverse-relation",
    )

    # extras 已写盘
    assert (paths.wiki_concepts / "old-extra.md").exists()
    # audit 日志记录了 reverse-relation 事件
    log_text = paths.llm_wiki_log.read_text(encoding="utf-8")
    assert "reverse-relation" in log_text, (
        f"audit log must record the custom event, got: {log_text[-400:]}"
    )


@pytest.mark.asyncio
async def test_generate_ingest_collects_extra_page_broken_refs(tmp_path: Path) -> None:
    """Phase 3 实测回归：generate_ingest 的 missing_slugs 必须覆盖 extras
    反向边引入的断链（collect 在 _compute_reverse_relations 之后执行）。

    场景：磁盘有存量页 `存量目标`；新页 `新页` 引用它 → extras 加载存量页
    并加反向边；若存量页自身（或反向边）引用了不存在页，该断链必须入
    meta["missing_slugs"]（M1 不再残留）。
    """
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # 磁盘存量页：自身带指向不存在页的 relation
    from src.wiki.features.relations import Relation
    write_page(paths, WikiPage(
        id="存量目标", title="存量目标", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], body="存量内容。",
        relations=[Relation(target_id="幽灵存量引用", type="references")],
    ))
    raw = paths.raw_sources / "src2.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("新源内容。", encoding="utf-8")

    script = [{
        "pages": [{
            "id": "新页", "type": "concept", "title": "新页",
            "slots": {
                "definition": "新页定义，内容足够长。",
                "characteristics": ["特征"],
                "examples": ["例子"],
                "related_concepts": ["[[存量目标]]"],
                "references": ["[[source-补充教程]]"],
            },
            "relations": [{"target": "存量目标", "type": "references"}],
        }],
    }]
    provider = ScriptedLLMProvider(script)

    pages, extras, meta = await generate_ingest(
        paths=paths, source_path=raw, source_text="新源内容。",
        provider=provider, task_id="kb-extra-gap",
    )
    assert any(p.id == "存量目标" for p in extras), "存量目标 应作为 extras 加载"
    missing = {m["slug"] for m in (meta.get("missing_slugs") or [])}
    # extras 页（存量目标）自身的幽灵引用必须被采集（Phase 3 实测修复）
    assert "幽灵存量引用" in missing, (
        f"extras 页的断链必须入 meta['missing_slugs']，got: {sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_generate_ingest_filters_illegal_relations(tmp_path: Path) -> None:
    """Phase 3 实测回归（M9）：非法 relation 类型（非 17 型 / 非 x-*）被过滤。

    JSON schema enum 只约束新 LLM 输出；存量页（extras 反向边合并）可能携带
    历史非法 relation（`related_to` / `contrasts` / `part_of` 等）。generate_ingest
    必须对 pages + extras 统一过滤，保证批内页 lint LINT-ILLEGAL-RELATION = 0。
    """
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # 磁盘存量页：带非法 relation（模拟历史遗留）
    from src.wiki.features.relations import Relation
    write_page(paths, WikiPage(
        id="存量带非法边", title="存量带非法边", type=PageType.CONCEPT,
        sources=["raw/sources/a.md"], body="存量内容。",
        relations=[
            Relation(target_id="幽灵", type="references"),
            Relation(target_id="另一个", type="related_to"),   # 非法
            Relation(target_id="第三个", type="part_of"),      # 非法
        ],
    ))
    raw = paths.raw_sources / "src3.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("源内容。", encoding="utf-8")

    script = [{
        "pages": [{
            "id": "新页2", "type": "concept", "title": "新页2",
            "slots": {
                "definition": "定义内容足够长。",
                "characteristics": ["特征"],
                "examples": ["例子"],
                "related_concepts": ["[[存量带非法边]]"],
                "references": ["[[source-补充教程]]"],
            },
            "relations": [{"target": "存量带非法边", "type": "references"}],
        }],
    }]
    provider = ScriptedLLMProvider(script)

    pages, extras, _meta = await generate_ingest(
        paths=paths, source_path=raw, source_text="源内容。",
        provider=provider, task_id="kb-m9",
    )
    # 本批新页 relations 无非法类型
    from src.wiki.features.lint import _BUILTIN_RELATIONS
    for p in pages:
        for r in (p.relations or []):
            assert r.type in _BUILTIN_RELATIONS or r.type.startswith("x-"), (
                f"batch page {p.id} has illegal relation {r.type}"
            )
    # extras（存量页）的非法 relation 被清理，合法保留
    extra = next(p for p in extras if p.id == "存量带非法边")
    types = {r.type for r in (extra.relations or [])}
    assert "related_to" not in types and "part_of" not in types, (
        f"extras illegal relations must be filtered, got {types}"
    )
    assert "references" in types, "legal relation must be preserved"


# ---------------------------------------------------------------------------
# 计划 2026-08-18 Task 3：commit_ingest 统一标签规范化兜底
# （pages + extra_pages 写盘前统一经过 tag_namespace.normalize_tags）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_ingest_normalizes_pages_tags(tmp_path: Path) -> None:
    """Task 3：pages 携带 legacy/非法标签时，落盘前统一规范化。

    ``func/教程`` 映射为 ``功能/教程``、``genre/玄幻`` 映射为 ``题材/玄幻``，
    并按兼容政策（策略 1）自动补 ``素材/ugc`` + ``可信度/ugc``。
    """
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "t3-pages.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    page = WikiPage(
        id="t3-page", title="T3页", type=PageType.CONCEPT,
        sources=["raw/sources/t3-pages.md"],
        body="## 定义\n\n内容。", grade="B",
        created_at=now, updated_at=now,
        tags=["func/教程", "genre/玄幻"],
    )
    await commit_ingest(paths=paths, source_path=raw, pages=[page],
                        task_id="kb-t3")

    on_disk = read_page(paths.wiki_concepts / "t3-page.md")
    assert on_disk.tags == ["功能/教程", "题材/玄幻", "素材/ugc", "可信度/ugc"], (
        f"commit_ingest must normalize page tags before write, got: {on_disk.tags}"
    )


@pytest.mark.asyncio
async def test_commit_ingest_normalizes_extra_pages_tags_and_audits(
        tmp_path: Path, caplog) -> None:
    """Task 3：extra_pages（存量反向边页）携带 legacy 标签时落盘前规范化。

    无法安全映射的标签（``func/结构``、``genre/平台``）被删除并产生
    TAG-REMOVED 审计日志；规范化不导致 AtomicContext 回滚（写盘成功）。
    """
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "t3-extra.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    page = WikiPage(
        id="t3-new", title="T3新页", type=PageType.SOURCE,
        sources=["raw/sources/t3-extra.md"],
        body="## 摘要\n\n内容。", grade="A",
        created_at=now, updated_at=now,
    )
    extra = WikiPage(
        id="t3-extra", title="T3存量", type=PageType.CONCEPT,
        sources=[], body="存量内容。", grade="C",
        created_at=now, updated_at=now,
        tags=["func/结构", "genre/平台", "功能/教程"],
    )
    with caplog.at_level(logging.WARNING, logger="src.pipeline.ingest"):
        await commit_ingest(paths=paths, source_path=raw, pages=[page],
                            extra_pages=[extra], task_id="kb-t3-extra")

    on_disk = read_page(paths.wiki_concepts / "t3-extra.md")
    # func/结构、genre/平台 值域非法且无法安全映射 → 删除；功能/教程 保留 + 补 mandatory
    assert on_disk.tags == ["功能/教程", "素材/ugc", "可信度/ugc"], (
        f"commit_ingest must normalize extra_pages tags, got: {on_disk.tags}"
    )
    # 审计日志记录 removal（页面 id + 原标签，不含凭据）
    audit_msgs = [r.message for r in caplog.records]
    assert any("TAG-REMOVED" in m and "t3-extra" in m and "func/结构" in m
               for m in audit_msgs), (
        f"audit log must record TAG-REMOVED, got: {audit_msgs}"
    )


@pytest.mark.asyncio
async def test_commit_ingest_leaves_clean_tags_untouched(tmp_path: Path) -> None:
    """Task 3：已合规标签页面（含 mandatory）落盘后不变（规范化零副作用）。"""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "t3-clean.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(time.time() * 1000)
    page = WikiPage(
        id="t3-clean", title="T3干净", type=PageType.CONCEPT,
        sources=["raw/sources/t3-clean.md"],
        body="## 定义\n\n内容。", grade="B",
        created_at=now, updated_at=now,
        tags=["题材/玄幻", "素材/ugc", "可信度/ugc"],
    )
    await commit_ingest(paths=paths, source_path=raw, pages=[page],
                        task_id="kb-t3-clean")

    on_disk = read_page(paths.wiki_concepts / "t3-clean.md")
    assert on_disk.tags == ["题材/玄幻", "素材/ugc", "可信度/ugc"]


# ---------------------------------------------------------------------------
# 计划 2026-08-18 Task 2：统一 Target Resolver 重写 body wikilink + relation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_ingest_rewrites_legacy_hash_source_link(tmp_path: Path) -> None:
    """Task 2：LLM 输出旧 hash + 标题丢词的 source 链接（batch 9 根因）
    → generate_ingest 后 body wikilink 与 relation target 均指向 canonical
    source slug。"""
    from tests.support.test_helpers import ScriptedLLMProvider
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "入门教程角色篇完善小说角色的技法.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("# 角色技法\n\n内容", encoding="utf-8")

    provider = ScriptedLLMProvider([{
        "pages": [
            {"id": "src", "type": "source", "title": "源",
             "slots": {"source_meta": "sm", "summary": "S",
                       "key_points": ["k"], "extracted_concepts": ["[[概念甲]]"]}},
            {"id": "飞书云文档", "type": "entity", "title": "飞书云文档",
             "slots": {"related": ["[[入门教程角色篇完善小说的技法-e8ca1866]]"],
                       "summary": "S"},
             "relations": [{"target": "入门教程角色篇完善小说的技法-e8ca1866",
                            "type": "references", "weight": 0.9, "context": "c"}]},
        ]
    }])
    pages, _extra, meta = await generate_ingest(
        paths=paths, source_path=raw, source_text="# 角色技法\n\n内容",
        provider=provider, task_id="kb-t2")
    src_slug = meta.get("source_slug")
    assert src_slug, meta
    by_id = {p.id: p for p in pages}
    ent = by_id["飞书云文档"]
    assert f"[[{src_slug}]]" in ent.body, ent.body
    assert any(r.target_id == src_slug for r in ent.relations), ent.relations


# ---------------------------------------------------------------------------
# 计划 2026-08-18 Task 3：finalize_generated_page 字段 owner 边界
# ---------------------------------------------------------------------------


def test_finalize_generated_page_overrides_system_fields():
    """Task 3：LLM 提供的非法系统字段由脚本最终裁定。"""
    from src.pipeline.ingest import finalize_generated_page
    page = WikiPage(
        id=" 带空格 ", title=" 标题 ", type=PageType.CONCEPT,
        grade="Z", processing_depth="bogus", created_at=0, updated_at=0,
        body="b", custom_type="",
    )
    finalize_generated_page(page, WikiPaths("."), now=123)
    assert page.id == "带空格"
    assert page.title == "标题"
    assert page.grade == "B"
    assert page.processing_depth == "concept"
    assert page.created_at == 123
    assert page.updated_at == 123
    # 已有时间戳不被覆盖（reingest 保留首次创建时间）
    page2 = WikiPage(id="a", title="A", type=PageType.CONCEPT,
                     created_at=111, updated_at=222)
    finalize_generated_page(page2, WikiPaths("."), now=999)
    assert page2.created_at == 111
    assert page2.updated_at == 222
    # Task 4：relation weight 归一化（越界/NaN → 1.0，合法值保留）
    from src.wiki.features.relations import Relation
    page3 = WikiPage(id="w", title="W", type=PageType.CONCEPT)
    page3.relations = [
        Relation(target_id="x", type="references", weight=5.0),
        Relation(target_id="y", type="references", weight=float("nan")),
        Relation(target_id="z", type="references", weight=0.3),
    ]
    finalize_generated_page(page3, WikiPaths("."), now=1)
    assert [r.weight for r in page3.relations] == [1.0, 1.0, 0.3]
