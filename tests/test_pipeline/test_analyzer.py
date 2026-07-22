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