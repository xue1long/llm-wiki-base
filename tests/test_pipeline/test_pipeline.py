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
        {"summary": "About backprop.", "key_facts": [], "entities": [],
         "concepts": [{"name": "Backprop", "slug": "backprop", "context": "...", "confidence": 0.9}],
         "suggested_pages": [{"type": "source", "slug": "test", "title": "Test", "reasoning": "..."}],
         "links_to_existing": []},
        {"pages": [{"id": "test", "type": "source", "title": "Test",
                    "frontmatter_extra": {},
                    "slots": {"source_meta": "sm", "summary": "Body content",
                              "key_points": ["kp"], "extracted_concepts": ["c"]}}]},
    ])

    pages = await run_ingest(
        paths=p, source_path=raw, source_text="PDF content about backprop",
        provider=provider,
    )
    # When the LLM emits a source-type page (slug="test"), the pipeline's
    # task-id fallback (kb-{task_id}) is redundant and would create a
    # duplicate source page. After dedup fix, only the LLM's page remains.
    assert len(pages) == 1, (
        f"expected exactly 1 page (LLM's source page); got {[(p.id, p.type) for p in pages]}"
    )
    page_ids = {p.id for p in pages}
    assert page_ids == {"test"}, f"expected only 'test' in {page_ids}"
    assert not any(p.id.startswith("kb-") for p in pages), (
        f"kb-* fallback must NOT be added when LLM already produced a source page"
    )
    assert (p.wiki_sources / "test.md").exists()
    assert "test" in p.llm_wiki_index.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collector_done_triggers_run_ingest(tmp_path, monkeypatch):
    """Integration: collector:done payload drives run_ingest and writes pages."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "x.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("content", encoding="utf-8")

    provider = ScriptedLLMProvider([
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [{"type": "source", "slug": "x", "title": "X", "reasoning": "r"}],
         "links_to_existing": []},
        {"pages": [{"id": "x", "type": "source", "title": "X",
                    "frontmatter_extra": {},
                    "slots": {"source_meta": "sm", "summary": "b",
                              "key_points": ["kp"], "extracted_concepts": ["c"]}}]},
    ])
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: p)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: provider)

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
    assert (p.wiki_sources / "x.md").exists()
    assert "x" in p.llm_wiki_index.read_text(encoding="utf-8")


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
        {"summary": "x", "key_facts": [], "entities": [], "concepts": [],
         "suggested_pages": [
             {"type": "concept", "slug": "only-concept", "title": "Only",
              "reasoning": "r"},
         ],
         "links_to_existing": []},
        {"pages": [
            {"id": "only-concept", "type": "concept", "title": "Only",
             "frontmatter_extra": {},
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
    assert "only-concept" in page_ids
    # Source page still created (always, when a source path exists)
    source_pages = [pid for pid in page_ids if pid != "only-concept"]
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
