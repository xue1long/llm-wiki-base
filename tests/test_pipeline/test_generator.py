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


# ---------------------------------------------------------------------------
# O-7: _render_template_section uses render_for_prompt() (compact + optional
# annotations) instead of dumping raw body_markdown
# ---------------------------------------------------------------------------

def test_render_template_section_compact_with_optional_annotations(tmp_path):
    """Prompt section uses render_for_prompt() — compact + optional annotations.

    Regression guard for the O-7 refactor: previously the generator
    dumped each template's raw body_markdown into the prompt (verbose,
    no hint about which sections are optional). After O-7 it routes
    through render_for_prompt() which annotates optional slots.
    """
    from src.pipeline.generator import _render_template_section

    # `tmp_path` is a fresh project root with no overrides → bundled
    # templates apply. The bundled entity template has `<!-- slot:aliases? -->`
    # which render_for_prompt() marks with `_(optional)_`.
    out = _render_template_section(tmp_path)
    assert "### entity" in out
    assert "<!-- slot:aliases? -->  _(optional)_" in out
    # Bundled concept template has no optional slots — must NOT be annotated
    assert "<!-- slot:definition -->" in out
    # The render-for-prompt path is compact: no blank line between
    # heading and its slot markers.
    assert "## 定义\n<!-- slot:definition -->" in out


def test_render_template_section_falls_back_when_no_bundled(tmp_path, monkeypatch):
    """When list_resolved() raises, the section reports 'no templates available'.

    The generator imports list_resolved lazily inside the function body,
    so we patch the source module (src.wiki.templates.list_resolved)
    rather than a name in src.pipeline.generator's namespace.
    """
    from src.pipeline.generator import _render_template_section

    def _raise(*_a, **_k):
        raise RuntimeError("simulated bundled dir missing")

    monkeypatch.setattr("src.wiki.templates.list_resolved", _raise)
    out = _render_template_section(tmp_path)
    assert "no templates available" in out.lower()
