import asyncio
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.pipeline import run_ingest
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
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

    # Pass a stable task_id we can check for.
    test_task_id = f"kb-test-{_uuid.uuid4().hex[:8]}"
    pages = await run_ingest(
        paths=p, source_path=raw, source_text="content",
        provider=provider, task_id=test_task_id,
    )
    page_ids = {p.id for p in pages}
    assert "only-concept" in page_ids
    # task-id fallback present (no LLM-emitted source page to dedup against)
    assert test_task_id in page_ids, (
        f"kb-* fallback should exist when no source page emitted; got {page_ids}"
    )
    assert (p.wiki_sources / f"{test_task_id}.md").exists()
