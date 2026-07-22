import asyncio
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.pipeline import run_ingest
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.events.events import CollectorDonePayload
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
                    "frontmatter_extra": {}, "body_markdown": "Body content"}]},
    ])

    pages = await run_ingest(
        paths=p, source_path=raw, source_text="PDF content about backprop",
        provider=provider,
    )
    assert len(pages) == 1
    assert pages[0].id == "test"
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
                    "frontmatter_extra": {}, "body_markdown": "b"}]},
    ])
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda: p)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda: provider)

    payload = CollectorDonePayload(task_id="t1", raw_path=str(raw), content="content")
    await pipeline_mod._on_collector_done(payload)
    assert (p.wiki_sources / "x.md").exists()
    assert "x" in p.llm_wiki_index.read_text(encoding="utf-8")
