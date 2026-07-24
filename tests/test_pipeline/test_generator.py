# tests/test_pipeline/test_generator.py
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.schemas import AnalysisResult, EntityMention, PageSpec
from src.pipeline.generator import generate
from src.wiki.core.types import PageType, WikiPage


@pytest.mark.asyncio
async def test_generate_returns_pages(tmp_path):
    from src.wiki.storage.ensure import ensure_knowledge_base
    ensure_knowledge_base(tmp_path)
    from src.wiki.core.paths import WikiPaths
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


@pytest.mark.asyncio
async def test_generate_emits_relations(tmp_path):
    """Generator populates WikiPage.relations from LLM response."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[PageSpec(type="source", slug="kb-1", title="T", reasoning="r")],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "T",
             "frontmatter_extra": {},
             "body_markdown": "B",
             "relations": [{"target": "other", "type": "references", "weight": 0.8}]},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert len(pages[0].relations) == 1
    assert pages[0].relations[0].target_id == "other"
    assert pages[0].relations[0].type == "references"


@pytest.mark.asyncio
async def test_generate_forwards_v22_fields_from_suggested_pages(tmp_path):
    """Generator passes grade/processing_depth/is_immutable from each
    suggested_page dict through to the constructed WikiPage."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="Article", reasoning="r",
                     grade="A", processing_depth="memory", is_immutable=True),
        ],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "Article",
             "grade": "A", "processing_depth": "memory", "is_immutable": True,
             "body_markdown": "B"},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert pages[0].grade == "A"
    assert pages[0].processing_depth == "memory"
    assert pages[0].is_immutable is True


@pytest.mark.asyncio
async def test_generate_uses_v22_defaults_when_missing(tmp_path):
    """When the LLM response omits grade/processing_depth/is_immutable,
    the constructed WikiPage still gets the v2.2 defaults (B / concept / False).
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[PageSpec(type="source", slug="kb-1", title="T", reasoning="r")],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "T", "body_markdown": "B"},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert pages[0].grade == "B"
    assert pages[0].processing_depth == "concept"
    assert pages[0].is_immutable is False
