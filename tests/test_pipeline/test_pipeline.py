# tests/test_pipeline/test_pipeline.py
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.pipeline import run_ingest
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.types import PageType


@pytest.mark.asyncio
async def test_run_ingest_full_pipeline(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    raw = p.raw_sources / "test.pdf"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"fake pdf content")

    provider = ScriptedLLMProvider([
        # Analyzer
        {"summary": "About backprop.", "key_facts": [], "entities": [],
         "concepts": [{"name": "Backprop", "slug": "backprop", "context": "...", "confidence": 0.9}],
         "suggested_pages": [{"type": "source", "slug": "test", "title": "Test", "reasoning": "..."}],
         "links_to_existing": []},
        # Generator
        {"pages": [{"id": "test", "type": "source", "title": "Test",
                    "frontmatter_extra": {}, "body_markdown": "Body content"}]},
    ])

    pages = await run_ingest(
        paths=p, source_path=raw, source_text="PDF content about backprop",
        provider=provider,
    )
    assert len(pages) == 1
    assert pages[0].id == "test"
    # Page written
    assert (p.wiki_sources / "test.md").exists()
    # Index updated
    assert "test" in p.llm_wiki_index.read_text(encoding="utf-8")