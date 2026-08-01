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

import time
from pathlib import Path

import pytest

from src.pipeline.ingest import (
    commit_ingest,
    generate_ingest,
    run_ingest,
)
from src.shared.test_helpers import ScriptedLLMProvider
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.relations import Relation
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


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
        "source_path",
        "source_text",
        "task_id",
        "existing_wiki_index",
        "source_slug",
        "downstream_count",
        "has_analysis",
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

    result = await commit_ingest(
        paths=paths,
        source_path=raw,
        pages=pages,
        extra_pages=extra_pages,
        task_id="kb-commit",
    )

    assert result is pages, "commit_ingest returns the pages it wrote"
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
    raw.write_text("这是一段用于测试的共享源文档内容。", encoding="utf-8")

    source_text = "这是一段用于测试的共享源文档内容。"

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
    pages_commit = await commit_ingest(
        paths=paths_b,
        source_path=raw,
        pages=pages_gen,
        extra_pages=extra_gen,
        task_id="kb-run",
    )

    assert _page_sig(pages_run) == _page_sig(pages_commit), (
        "run_ingest and generate+commit must produce identical page sets"
    )
    assert len(pages_run) == len(pages_commit)


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
