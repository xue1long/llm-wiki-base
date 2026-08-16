import asyncio
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.pipeline import run_ingest
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType
from src.events.events import CollectorDonePayload
from src.queue import __reset_for_testing, enqueue_task, get_queue, get_default_queue_service
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache
import src.pipeline.pipeline as pipeline_mod


@pytest.mark.asyncio
async def test_run_ingest_full_pipeline(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "test.pdf"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"fake pdf content")

    provider = ScriptedLLMProvider([
        # Entry 0: unified format (consumed by unified_generate first attempt
        # if it parses; otherwise triggers retry/fallback). Must have "pages"
        # key to produce pages.
        {"pages": [{"id": "test", "type": "source", "title": "Test",
                    "slots": {"source_meta": "sm", "summary": "Body content",
                              "key_points": ["kp"], "extracted_concepts": ["c"],
                              "main_content": ""}}]},
    ])

    pages = await run_ingest(
        paths=p, source_path=raw, source_text="PDF content about backprop",
        provider=provider,
    )
    # Deterministic source-page slug rewrites LLM's "test" to "test-<hash>".
    assert len(pages) == 1, (
        f"expected exactly 1 page (LLM's source page); got {[(p.id, p.type) for p in pages]}"
    )
    page_ids = {p.id for p in pages}
    source_page_id = next(iter(page_ids))
    assert source_page_id.startswith("test-"), (
        f"source page id should start with 'test-', got {source_page_id!r}"
    )
    assert not any(p.id.startswith("kb-") for p in pages), (
        f"kb-* fallback must NOT be added when LLM already produced a source page"
    )
    assert (p.wiki_sources / f"{source_page_id}.md").exists()
    assert source_page_id in p.llm_wiki_index.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collector_done_triggers_run_ingest(tmp_path, monkeypatch):
    """Integration: collector:done payload drives run_ingest and writes pages."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "x.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("content", encoding="utf-8")

    provider = ScriptedLLMProvider([
        # Entry 0: unified format — must have "pages" key.
        {"pages": [{"id": "x", "type": "source", "title": "X",
                    "slots": {"source_meta": "sm", "summary": "b",
                              "key_points": ["kp"], "extracted_concepts": ["c"]}}]},
    ])
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: p)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda project_id=None: provider)

    get_idempotency_cache().clear()
    __reset_for_testing()
    service = get_default_queue_service()
    service.pause()
    task_id = enqueue_task("x.md", SourceType.FILE, "pipeline-integration")
    # Drive the task to RUNNING and mark in-flight via the service
    task = service.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    service.backend.save(task)
    service.tracker.acquire(task_id)
    payload = CollectorDonePayload(task_id=task_id, raw_path=str(raw), content="content")
    await pipeline_mod._on_collector_done(payload)
    # Deterministic source-page slug: {stem}-{hash}
    source_page = next((p.wiki_sources.glob("x-*.md")), None)
    assert source_page is not None, (
        f"expected source page x-<hash>.md in {p.wiki_sources}"
    )
    source_id = source_page.stem
    assert source_id in p.llm_wiki_index.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_run_ingest_kb_task_id_fallback_when_llm_omits_source_page(tmp_path):
    """Inverse guard: when the LLM does NOT emit any source-type page,
    the kb-{task_id} fallback must still be added so the wiki always
    has a stable attachment point. (Pairs with the dedup test above.)
    """
    import uuid as _uuid
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "nope.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("content", encoding="utf-8")

    # LLM only generates concept pages, NO source-type page emitted.
    provider = ScriptedLLMProvider([
        # Entry 0: unified format — concept page, no source.
        {"pages": [
            {"id": "only-concept", "type": "concept", "title": "Only",
             "slots": {"definition": "concept body",
                       "characteristics": ["c"], "examples": ["e"],
                       "related_concepts": ["rc"], "references": ["r"]}},
        ]},
    ])

    # task_id is recorded for audit (in source-meta slot) but no longer
    # used as the source-page filename — that's now derived from the
    # raw file's stem with a short path-hash suffix.
    test_task_id = f"kb-test-{_uuid.uuid4().hex[:8]}"
    pages = await run_ingest(
        paths=p, source_path=raw, source_text="content",
        provider=provider, task_id=test_task_id,
    )
    page_ids = {p.id for p in pages}
    assert "only" in page_ids  # slug from title, not LLM's id
    # Source page still created (always, when a source path exists)
    source_pages = [pid for pid in page_ids if pid != "only"]
    assert len(source_pages) == 1, f"expected 1 source page, got {source_pages}"
    source_pid = source_pages[0]
    # Source page id is {stem}-{8hex}; stem is 'nope' since raw is 'nope.md'
    assert source_pid.startswith("nope-"), (
        f"source id should start with 'nope-', got {source_pid!r}"
    )
    assert len(source_pid) == len("nope-") + 8, (
        f"expected 8-hex suffix on {source_pid!r}"
    )
    assert (p.wiki_sources / f"{source_pid}.md").exists()


# ---------------------------------------------------------------------------
# v2.4 source-page id strategy: {NFC(stem)}-{path_hash_8_hex}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_page_uses_chinese_stem_with_path_hash(tmp_path):
    """Source page id is the raw file's Chinese stem + an 8-hex hash; no pinyin."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "必备资料15顺眼谈文章的画面感.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("body", encoding="utf-8")

    provider = ScriptedLLMProvider([
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [], "links_to_existing": []},
        {"pages": []},
    ])
    pages = await run_ingest(
        paths=p, source_path=raw, source_text="body",
        provider=provider, task_id="kb-test-stem",
    )
    page = next(p for p in pages if p.type == PageType.SOURCE)
    expected_stem = "必备资料15顺眼谈文章的画面感"
    assert page.id.startswith(expected_stem + "-"), (
        f"source id should start with {expected_stem!r}-, got {page.id!r}"
    )
    # 8-hex suffix (no pinyin, no kb-*).
    suffix = page.id[len(expected_stem) + 1:]
    assert len(suffix) == 8 and all(c in "0123456789abcdef" for c in suffix), (
        f"expected 8-hex suffix, got {suffix!r}"
    )
    # File on disk matches.
    assert (p.wiki_sources / f"{page.id}.md").exists()
    # task_id is NOT the filename anymore, but the source-meta slot
    # still records it for audit.
    assert "- 任务 ID: `kb-test-stem`" in page.body or "kb-test-stem" in page.body


@pytest.mark.asyncio
async def test_source_page_title_strips_md_suffix(tmp_path):
    """Source page title is the stem without '.md' (was a tiny bug)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "必备资料15顺眼谈文章的画面感.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("body", encoding="utf-8")

    provider = ScriptedLLMProvider([
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [], "links_to_existing": []},
        {"pages": []},
    ])
    pages = await run_ingest(
        paths=p, source_path=raw, source_text="body",
        provider=provider, task_id="kb-test-title",
    )
    page = next(p for p in pages if p.type == PageType.SOURCE)
    assert page.title == "必备资料15顺眼谈文章的画面感", (
        f"title should drop .md suffix, got {page.title!r}"
    )


@pytest.mark.asyncio
async def test_source_page_id_stable_across_reingest(tmp_path, monkeypatch):
    """Re-ingesting the same source path gives the same id (deterministic hash)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "stable-source.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("body", encoding="utf-8")

    provider1 = ScriptedLLMProvider([
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [], "links_to_existing": []},
        {"pages": []},
    ])
    pages1 = await run_ingest(
        paths=p, source_path=raw, source_text="body",
        provider=provider1, task_id="kb-test-stable-1",
    )
    source1 = next(p for p in pages1 if p.type == PageType.SOURCE)

    # Re-ingest: clear in-memory idempotency cache so the same source
    # actually re-enters the pipeline.
    from src.utils import idempotency as _idem
    _idem._cache.clear() if hasattr(_idem, "_cache") else None
    provider2 = ScriptedLLMProvider([
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [], "links_to_existing": []},
        {"pages": []},
    ])
    pages2 = await run_ingest(
        paths=p, source_path=raw, source_text="body",
        provider=provider2, task_id="kb-test-stable-2",
    )
    source2 = next(p for p in pages2 if p.type == PageType.SOURCE)

    # Same source path → same id, even with different task_ids.
    assert source1.id == source2.id, (
        f"id should be deterministic for same source path; "
        f"got {source1.id!r} vs {source2.id!r}"
    )
    assert source1.id.startswith("stable-source-"), (
        f"id should start with 'stable-source-', got {source1.id!r}"
    )
    assert len(source1.id) == len("stable-source-") + 8


# ---------------------------------------------------------------------------
# Phase 2 tests: unified_generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unified_generate_produces_pages(tmp_path):
    """unified_generate should parse source text and return WikiPage list in one call."""
    from src.pipeline.generator import unified_generate
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "backprop", "type": "concept", "title": "反向传播",
             "slots": {"definition": "反向传播是训练神经网络的核心算法。",
                       "characteristics": ["梯度计算", "链式法则"],
                       "examples": ["示例1"], "related_concepts": ["[[gradient-descent]]"],
                       "references": ["test"]}},
        ]},
    ])

    pages = await unified_generate(
        source_text="反向传播（backpropagation）是训练神经网络的核心算法。",
        source_path="test.pdf",
        folder_context="",
        paths=p,
        existing_wiki_index="",
        provider=provider,
    )

    assert len(pages) == 1
    page = pages[0]
    assert page.id == "反向传播"  # slug from CJK title, not LLM's id
    assert page.type == PageType.CONCEPT
    assert page.title == "反向传播"
    assert "反向传播是训练神经网络的核心算法" in page.body


@pytest.mark.asyncio
async def test_unified_generate_injects_wiki_purpose(tmp_path):
    """The default one-pass ingestion path must receive purpose.md text."""
    from src.pipeline.generator import unified_generate
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    provider = ScriptedLLMProvider([{"pages": []}])

    await unified_generate(
        source_text="source",
        source_path="test.md",
        folder_context="",
        paths=p,
        existing_wiki_index="",
        provider=provider,
        purpose_content="Prefer evidence-backed research notes.",
    )

    assert "Prefer evidence-backed research notes." in str(provider.calls[0])


@pytest.mark.asyncio
async def test_unified_generate_truncates_large_source(tmp_path):
    """Source text > MAX_SOURCE_CHARS should be truncated to control prompt size."""
    from src.pipeline.generator import unified_generate
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    # Build a source that exceeds the 24000-char truncation limit
    large_text = "长文本内容。" * 5000  # ~30000 chars, well over 24000 limit

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "summary", "type": "concept", "title": "摘要",
             "slots": {"definition": "概括。",
                       "characteristics": ["特征一"],
                       "examples": ["例子一"],
                       "related_concepts": ["[[other]]"],
                       "references": ["[[test]]"]}},
        ]},
    ])

    pages = await unified_generate(
        source_text=large_text,
        source_path="large.txt",
        folder_context="",
        paths=p,
        existing_wiki_index="",
        provider=provider,
    )

    # Still produces pages despite truncation
    assert len(pages) == 1
    # Verify the source was truncated (prompt contains truncation marker)
    first_call_content = str(provider.calls[0])
    assert "[... 文本过长，已截断 ...]" in first_call_content, (
        "truncation marker should appear in prompt for large source"
    )


@pytest.mark.asyncio
async def test_unified_generate_dedups_relations(tmp_path):
    """Duplicate relations (same slugified target) should be merged, keeping highest weight."""
    from src.pipeline.generator import unified_generate
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "concept-a", "type": "concept", "title": "概念A",
             "slots": {"definition": "A的定义。",
                       "characteristics": ["c1"], "examples": ["e1"],
                       "related_concepts": ["[[concept-b]]"], "references": []},
             "relations": [
                 {"target": "concept-b", "type": "references", "weight": 0.9, "context": "first"},
                 {"target": "concept-b", "type": "references", "weight": 0.5, "context": "second dup"},
                 {"target": "concept-c", "type": "analogous_to", "weight": 0.7, "context": "unique"},
             ]},
        ]},
    ])

    pages = await unified_generate(
        source_text="概念A引用概念B。",
        source_path="test.md",
        folder_context="",
        paths=p,
        existing_wiki_index="",
        provider=provider,
    )

    assert len(pages) == 1
    rels = pages[0].relations
    # concept-b appears twice but deduped → 2 unique targets (concept-b, concept-c)
    assert len(rels) == 2, f"expected 2 deduped relations, got {len(rels)}: {rels}"
    # The kept concept-b relation should have weight 0.9 (highest)
    b_rel = [r for r in rels if r.target_id == "concept-b"]
    assert len(b_rel) == 1
    assert b_rel[0].weight == 0.9


# ---------------------------------------------------------------------------
# Phase 3 tests: run_batch_ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_ingest_processes_multiple_files(tmp_path):
    """run_batch_ingest should process multiple files concurrently."""
    from src.pipeline.ingest import run_batch_ingest
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    # Create 3 raw source files
    files = []
    for i in range(3):
        f = p.raw_sources / f"doc{i}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"Content of document {i}", encoding="utf-8")
        files.append(f)

    # Each file gets one unified response with all required slots filled.
    # Wikilinks point at the batch's own produced page (self-resolvable) so
    # the 1.3 missing-slug resolver does NOT fire a feedback retry that would
    # consume the next scripted entry (ScriptedLLMProvider pops on retry).
    provider = ScriptedLLMProvider([
        {"pages": [{"id": f"concept-{i}", "type": "concept", "title": f"概念{i}",
                    "slots": {"definition": f"内容{i}。",
                              "characteristics": [f"特征{i}"],
                              "examples": [f"例子{i}"],
                              "related_concepts": [f"[[concept-{i}]]"],
                              "references": [f"[[concept-{i}]]"]}}]}
        for i in range(3)
    ])

    results = await run_batch_ingest(
        paths=p,
        source_paths=files,
        provider=provider,
        concurrency=1,  # serial: avoids race on shared ScriptedLLMProvider
    )

    assert len(results) == 3
    for i, pages in enumerate(results):
        assert len(pages) >= 1, f"file {i} produced no pages"
        # Each should have at least the concept page + source page
        page_ids = {pg.id for pg in pages}
        assert f"概念-{i}" in page_ids  # slug from CJK title; CJK/ASCII boundary adds hyphen


@pytest.mark.asyncio
async def test_run_batch_ingest_exception_isolation(tmp_path):
    """When one file fails, other files should still succeed."""
    from src.pipeline.ingest import run_batch_ingest
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    files = []
    for i in range(3):
        f = p.raw_sources / f"doc{i}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"Content {i}", encoding="utf-8")
        files.append(f)

    # File 1 (doc1.md) will fail — provider raises on EVERY call for it.
    # Must fail all calls because run_ingest falls back from unified path
    # to two-step on first failure; the fallback would succeed otherwise.
    import json as _json
    from src.llm.base import LLMResponse

    class FailingProvider:
        """Provider that fails for doc1.md; succeeds for others."""
        def __init__(self):
            self.calls = []

        async def complete(self, messages=None, *, response_format=None, system=None, **kwargs):
            self.calls.append({"messages": messages, "schema": response_format})
            # Check if this call is for doc1 (the failing file)
            prompt_text = ""
            if messages:
                for m in messages:
                    prompt_text += str(m.get("content", ""))
            if "doc1" in prompt_text or "Content 1" in prompt_text:
                raise RuntimeError("injected failure for doc1")
            return LLMResponse(content=_json.dumps({
                "pages": [{"id": "concept-ok", "type": "concept",
                           "title": "概念OK",
                           "slots": {"definition": "x", "characteristics": ["c"],
                                     "examples": ["e"], "related_concepts": [],
                                     "references": []}}]
            }), model="mock")

    provider = FailingProvider()
    results = await run_batch_ingest(
        paths=p,
        source_paths=files,
        provider=provider,
        concurrency=1,
    )

    assert len(results) == 3
    # File 0: success
    assert len(results[0]) >= 1
    # File 1: failed → empty list (all attempts including fallback fail)
    assert results[1] == [], f"expected empty for failed file, got {results[1]}"
    # File 2: success (isolated from file 1's failure)
    assert len(results[2]) >= 1
