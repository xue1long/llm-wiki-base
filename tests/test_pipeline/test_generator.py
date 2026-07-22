# tests/test_pipeline/test_generator.py
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.schemas import AnalysisResult, EntityMention, PageSpec
from src.pipeline.generator import generate
from src.wiki.types import PageType, WikiPage


@pytest.mark.asyncio
async def test_generate_returns_pages(tmp_path):
    from src.wiki.ensure import ensure_knowledge_base
    ensure_knowledge_base(tmp_path)
    from src.wiki.paths import WikiPaths
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf",
        summary="Article summary.",
        entities=[EntityMention(name="Backprop", slug="backprop", type="concept", context="...", confidence=0.9)],
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="Article", reasoning="source page"),
            PageSpec(type="concept", slug="backprop", title="Backprop", reasoning="concept page"),
        ],
    )

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "Article",
             "frontmatter_extra": {"tags": ["concept"]},
             "body_markdown": "Article body"},
            {"id": "backprop", "type": "concept", "title": "Backprop",
             "frontmatter_extra": {"tags": []},
             "body_markdown": "Backprop body"},
        ]}
    ])

    pages = await generate(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
    )
    assert len(pages) == 2
    assert pages[0].id == "kb-1"
    assert pages[0].type == PageType.SOURCE
    assert pages[1].id == "backprop"
    assert pages[1].type == PageType.CONCEPT
