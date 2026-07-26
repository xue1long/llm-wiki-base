# tests/test_pipeline/test_analyzer.py
import json
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.schemas import AnalysisResult, EntityMention
from src.pipeline.analyzer import analyze


@pytest.mark.asyncio
async def test_analyze_returns_analysis_result():
    provider = ScriptedLLMProvider([{
        "summary": "An article about backprop.",
        "key_facts": ["Backprop is a key algorithm", "It uses gradient descent"],
        "entities": [
            {"name": "Backprop", "slug": "backprop", "type": "concept",
             "context": "Backpropagation algorithm", "confidence": 0.95}
        ],
        "concepts": [],
        "suggested_pages": [
            {"type": "source", "slug": "paper-1", "title": "Paper 1", "reasoning": "Source page"}
        ],
        "links_to_existing": []
    }])
    result = await analyze(
        source_text="Long text about backprop...",
        source_ext=".pdf",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
    )
    assert result.summary == "An article about backprop."
    assert len(result.entities) == 1
    assert result.entities[0].slug == "backprop"
    assert len(result.suggested_pages) == 1


@pytest.mark.asyncio
async def test_analyze_parses_v22_fields_from_llm():
    """When the LLM response includes v2.2 fields per suggested_page,
    the Analyzer must round-trip them into the resulting PageSpec."""
    provider = ScriptedLLMProvider([{
        "summary": "An article.",
        "key_facts": [],
        "entities": [],
        "concepts": [],
        "suggested_pages": [
            {
                "type": "source",
                "slug": "kb-1",
                "title": "Article",
                "reasoning": "primary source",
                "grade": "A",
                "processing_depth": "memory",
                "is_immutable": True,
                "tags": ["genre/noir", "func/reference"],
            },
        ],
        "links_to_existing": [],
    }])
    result = await analyze(
        source_text="body...",
        source_ext=".pdf",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
    )
    assert len(result.suggested_pages) == 1
    sp = result.suggested_pages[0]
    assert sp.grade == "A"
    assert sp.processing_depth == "memory"
    assert sp.is_immutable is True
    assert sp.tags == ["genre/noir", "func/reference"]


@pytest.mark.asyncio
async def test_analyze_uses_default_v22_fields_when_missing():
    """When the LLM response omits v2.2 fields, the resulting PageSpec
    uses the defaults (B / concept / False / [])."""
    provider = ScriptedLLMProvider([{
        "summary": "An article.",
        "key_facts": [],
        "entities": [],
        "concepts": [],
        "suggested_pages": [
            {"type": "source", "slug": "kb-1", "title": "T", "reasoning": "r"},
        ],
        "links_to_existing": [],
    }])
    result = await analyze(
        source_text="body...",
        source_ext=".pdf",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
    )
    sp = result.suggested_pages[0]
    assert sp.grade == "B"
    assert sp.processing_depth == "concept"
    assert sp.is_immutable is False
    assert sp.tags == []


@pytest.mark.asyncio
async def test_analyze_entity_missing_type_field_uses_default():
    """When the LLM response omits the 'type' field on an entity,
    the analyzer must not crash and must populate EntityMention.type
    with a sensible default ("concept") instead.
    """
    provider = ScriptedLLMProvider([{
        "summary": "Article without entity types.",
        "key_facts": [],
        # LLM returned these dicts but forgot to include 'type'
        "entities": [
            {"name": "Foo", "slug": "foo",
             "context": "Some context", "confidence": 0.5},
        ],
        "concepts": [],
        "suggested_pages": [
            {"type": "source", "slug": "kb-1", "title": "T", "reasoning": "r"},
        ],
        "links_to_existing": [],
    }])
    result = await analyze(
        source_text="body...",
        source_ext=".pdf",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
    )
    assert len(result.entities) == 1
    assert result.entities[0].name == "Foo"
    assert result.entities[0].type == "concept"


@pytest.mark.asyncio
async def test_analyzer_prompt_prohibits_chain_of_thought():
    """ANALYZER_PROMPT must explicitly forbid chain-of-thought / hidden
    reasoning /  thinking transcripts. Defense-in-depth: keeps `` reasoning
    traces out of the markdown body and prevents providers that emit
    DeepSeek-style `` blocks from leaking them into wiki pages.
    """
    provider = ScriptedLLMProvider([{
        "summary": "x", "key_facts": [], "entities": [],
        "concepts": [], "suggested_pages": [
            {"type": "source", "slug": "kb-1", "title": "T", "reasoning": "r"},
        ],
        "links_to_existing": [],
    }])
    await analyze(
        source_text="x", source_ext=".pdf", existing_wiki_index="",
        folder_context="", provider=provider,
    )

    call = provider.calls[0]
    msgs = call.get("messages") or []
    assert msgs and msgs[0].get("role") == "user"
    prompt = msgs[0]["content"]
    prompt_lower = prompt.lower()
    # Pick a directive phrasing; require a prohibition keyword near
    # one of the canonical CoT signals.
    forbid_found = False
    for kw in ("chain-of-thought", "chain of thought", "hidden reasoning",
               "thinking transcript", "thinking", "reasoning trace"):
        if kw in prompt_lower:
            line_idx = prompt_lower.find(kw)
            start = max(0, line_idx - 80)
            ctx = prompt_lower[start:line_idx + len(kw) + 80]
            if any(p in ctx for p in (
                "do not", "don't", "never", "no ", "avoid", "禁止", "不要",
            )):
                forbid_found = True
                break
    assert forbid_found, (
        "ANALYZER_PROMPT must include a directive forbidding chain-of-thought "
        "/ hidden reasoning / thinking transcripts."
    )
