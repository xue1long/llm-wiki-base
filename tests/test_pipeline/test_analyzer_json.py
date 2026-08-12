"""tests/test_pipeline/test_analyzer_json.py — JSON analyzer output with 3-tier validation."""
import pytest

from src.pipeline.analyzer import (
    AnalyzerOutputParser,
    ANALYZER_JSON_PROMPT,
    analyze,
)


def test_parser_keeps_only_declared_custom_type():
    raw = {
        "source_id": "raw/sources/x.md",
        "type": "concept",
        "custom_type": "thesis",
        "title": "T",
        "claims": [{"statement": "C", "confidence": 0.9, "evidence_refs": []}],
    }
    parser = AnalyzerOutputParser()
    assert parser.parse(raw, allowed_custom_types={"thesis"}).custom_type == "thesis"
    assert parser.parse(raw, allowed_custom_types={"finding"}).custom_type == ""
from src.pipeline.schemas import AnalysisResult
from src.knowledge.core.candidate import (
    KnowledgeCandidate,
    CandidateStatus,
)
from src.knowledge.core.object import KnowledgeType
from src.shared.test_helpers import ScriptedLLMProvider


# ---------------------------------------------------------------------------
# 1. AnalyzerOutputParser: valid JSON matching schema
# ---------------------------------------------------------------------------

def test_parser_accepts_valid_json_matching_schema():
    """Parser accepts a complete KnowledgeCandidate-shaped dict and returns
    a PENDING candidate with all fields populated correctly."""
    parser = AnalyzerOutputParser()
    raw = {
        "source_id": "raw/sources/doc1.md",
        "type": "concept",
        "title": "Backpropagation Algorithm",
        "claims": [
            {
                "statement": "Backprop is a key algorithm for training neural networks",
                "confidence": 0.95,
                "evidence_refs": [0],
            },
            {
                "statement": "It uses gradient descent to minimize loss",
                "confidence": 0.90,
                "evidence_refs": [0, 1],
            },
        ],
        "evidence": [
            {"source_path": "raw/sources/doc1.md", "page": 3, "quote": "Backprop computes gradients..."},
            {"source_path": "raw/sources/doc1.md", "page": 5, "quote": "Gradient descent updates weights..."},
        ],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc1.md")

    assert isinstance(candidate, KnowledgeCandidate)
    assert candidate.status == CandidateStatus.PENDING
    assert candidate.source_id == "raw/sources/doc1.md"
    assert candidate.type == KnowledgeType.CONCEPT
    assert candidate.title == "Backpropagation Algorithm"
    assert candidate.confidence == 1.0
    assert len(candidate.claims) == 2
    assert candidate.claims[0]["statement"] == "Backprop is a key algorithm for training neural networks"
    assert candidate.claims[0]["confidence"] == 0.95
    assert candidate.claims[0]["evidence_refs"] == [0]
    assert len(candidate.evidence) == 2
    assert candidate.evidence[0]["source_path"] == "raw/sources/doc1.md"
    assert candidate.evidence[0]["page"] == 3
    assert candidate.evidence[0]["quote"] == "Backprop computes gradients..."
    assert candidate.raw_llm_output == raw
    # id must be generated
    assert candidate.id
    assert len(candidate.id) > 0


# ---------------------------------------------------------------------------
# 2. Syntax check: invalid JSON (empty/invalid dict) -> REJECTED
# ---------------------------------------------------------------------------

def test_syntax_check_invalid_input_rejected():
    """When the parser receives a non-dict or empty-dict input
    (simulating a failed JSON parse after LLM retries), it returns
    a REJECTED candidate with zero confidence."""
    parser = AnalyzerOutputParser()

    # Non-dict input
    candidate = parser.parse(None, source_path="raw/sources/test.md")  # type: ignore[arg-type]
    assert candidate.status == CandidateStatus.REJECTED
    assert candidate.confidence == 0.0

    # Empty dict
    candidate2 = parser.parse({}, source_path="raw/sources/test.md")
    assert candidate2.status == CandidateStatus.REJECTED


# ---------------------------------------------------------------------------
# 3. Schema check: missing source_id -> REJECTED
# ---------------------------------------------------------------------------

def test_schema_check_missing_source_id_rejected():
    """source_id is required — without it the candidate is untraceable
    and must be REJECTED."""
    parser = AnalyzerOutputParser()
    raw = {
        "type": "concept",
        "title": "Some Concept",
        "claims": [{"statement": "A claim", "confidence": 0.9, "evidence_refs": []}],
        "evidence": [],
    }
    candidate = parser.parse(raw, source_path="raw/sources/other.md")
    assert candidate.status == CandidateStatus.REJECTED
    # source_id in the candidate should fall back to empty
    assert candidate.source_id == ""


# ---------------------------------------------------------------------------
# 4. Schema check: missing type -> default "concept", confidence *= 0.3
# ---------------------------------------------------------------------------

def test_schema_check_missing_type_defaulted():
    """When 'type' is missing from the LLM output, default to
    KnowledgeType.CONCEPT and decay confidence by 0.3."""
    parser = AnalyzerOutputParser()
    raw = {
        "source_id": "raw/sources/doc2.md",
        "title": "Gradient Descent",
        "claims": [
            {"statement": "GD converges to local minima", "confidence": 0.85, "evidence_refs": [0]},
        ],
        "evidence": [{"source_path": "raw/sources/doc2.md", "page": None, "quote": "GD works..."}],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc2.md")
    assert candidate.type == KnowledgeType.CONCEPT
    assert candidate.confidence == 0.3  # 1.0 * 0.3
    assert candidate.status == CandidateStatus.PENDING  # not rejected, just decayed


# ---------------------------------------------------------------------------
# 5. Schema check: missing title -> truncated from first claim, confidence *= 0.3
# ---------------------------------------------------------------------------

def test_schema_check_missing_title_truncated_from_claim():
    """When 'title' is missing, derive it from claims[0].statement
    (truncated to 80 chars) and decay confidence."""
    parser = AnalyzerOutputParser()
    long_statement = "A" * 120
    raw = {
        "source_id": "raw/sources/doc3.md",
        "type": "entity",
        "claims": [
            {"statement": long_statement, "confidence": 0.8, "evidence_refs": []},
            {"statement": "Another claim", "confidence": 0.7, "evidence_refs": []},
        ],
        "evidence": [],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc3.md")
    assert candidate.title == "A" * 80  # truncated to 80 chars
    assert candidate.confidence == 0.3  # 1.0 * 0.3
    assert candidate.status == CandidateStatus.PENDING


def test_schema_check_missing_title_short_claim():
    """When title is missing and first claim statement is short (< 80 chars),
    use the full statement as title."""
    parser = AnalyzerOutputParser()
    raw = {
        "source_id": "raw/sources/doc4.md",
        "type": "concept",
        "claims": [
            {"statement": "Short claim", "confidence": 0.5, "evidence_refs": []},
        ],
        "evidence": [],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc4.md")
    assert candidate.title == "Short claim"
    assert candidate.confidence == 0.3


# ---------------------------------------------------------------------------
# 6. Content check: empty claims -> confidence=0.3
# ---------------------------------------------------------------------------

def test_content_check_empty_claims_low_confidence():
    """When claims list is empty, set confidence=0.3 (flag for human review)
    but do NOT reject — the candidate may still be salvageable."""
    parser = AnalyzerOutputParser()
    raw = {
        "source_id": "raw/sources/doc5.md",
        "type": "concept",
        "title": "Empty Claims Doc",
        "claims": [],
        "evidence": [],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc5.md")
    assert candidate.confidence == 0.3
    assert candidate.claims == []
    assert candidate.status == CandidateStatus.PENDING  # not rejected, just low confidence


def test_content_check_combined_penalties():
    """Multiple schema violations compound confidence decay."""
    parser = AnalyzerOutputParser()
    # Missing both type AND title, AND empty claims
    raw = {
        "source_id": "raw/sources/doc6.md",
        "claims": [],
        "evidence": [],
    }
    candidate = parser.parse(raw, source_path="raw/sources/doc6.md")
    # type missing: * 0.3, title missing: * 0.3, empty claims: = 0.3
    # 1.0 * 0.3 * 0.3 = 0.09, then empty claims overrides to 0.3 independently
    # Actually: compound first, then empty claims check last
    # missing type: 1.0 * 0.3 = 0.3
    # missing title: 0.3 * 0.3 = 0.09
    # empty claims: 0.3 (set, not multiplied)
    assert candidate.confidence == 0.3
    assert candidate.type == KnowledgeType.CONCEPT


# ---------------------------------------------------------------------------
# 7. Config flag "markdown" preserves old behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_markdown_output_format_preserves_old_behavior():
    """When output_format='markdown' (the default), analyze() must return
    an AnalysisResult (not a KnowledgeCandidate) using the original prompt."""
    provider = ScriptedLLMProvider([{
        "summary": "A test analysis.",
        "key_facts": ["Fact 1"],
        "entities": [
            {"name": "Test Entity", "slug": "test-entity", "type": "concept",
             "context": "A test context", "confidence": 0.9},
        ],
        "concepts": [],
        "suggested_pages": [
            {"type": "source", "slug": "test-page", "title": "Test Page", "reasoning": "Source"},
        ],
        "links_to_existing": [],
    }])
    result = await analyze(
        source_text="Test source text for markdown mode.",
        source_ext=".md",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
        output_format="markdown",
    )
    assert isinstance(result, AnalysisResult)
    assert not isinstance(result, KnowledgeCandidate)
    assert result.summary == "A test analysis."
    assert len(result.entities) == 1
    assert result.entities[0].name == "Test Entity"


@pytest.mark.asyncio
async def test_json_output_format_returns_knowledge_candidate():
    """When output_format='json', analyze() uses the JSON prompt and
    returns a KnowledgeCandidate through AnalyzerOutputParser."""
    provider = ScriptedLLMProvider([{
        "source_id": "raw/sources/test.md",
        "type": "concept",
        "title": "Test Knowledge",
        "claims": [
            {"statement": "A test claim about knowledge", "confidence": 0.9, "evidence_refs": [0]},
        ],
        "evidence": [
            {"source_path": "raw/sources/test.md", "page": None, "quote": "test quote"},
        ],
    }])
    result = await analyze(
        source_text="Test source for JSON mode.",
        source_ext=".md",
        existing_wiki_index="",
        folder_context="",
        provider=provider,
        output_format="json",
    )
    assert isinstance(result, KnowledgeCandidate)
    assert result.status == CandidateStatus.PENDING
    assert result.title == "Test Knowledge"
    assert result.type == KnowledgeType.CONCEPT
    assert len(result.claims) == 1


# ---------------------------------------------------------------------------
# 8. ANALYZER_JSON_PROMPT is defined and contains key directives
# ---------------------------------------------------------------------------

def test_json_prompt_contains_schema_directives():
    """ANALYZER_JSON_PROMPT must instruct the LLM to output
    KnowledgeCandidate-shaped JSON."""
    prompt = ANALYZER_JSON_PROMPT
    assert "source_id" in prompt
    assert "claims" in prompt
    assert "evidence" in prompt
    assert "statement" in prompt
    assert "confidence" in prompt
    assert "evidence_refs" in prompt


def test_json_prompt_knowledge_types_derived_from_knowledge_type():
    """ANALYZER_JSON_PROMPT's type list must be derived from the
    KnowledgeType enum (all 8 knowledge-layer values), not a hardcoded string."""
    knowledge_types = "|".join(t.value for t in KnowledgeType)
    rendered = ANALYZER_JSON_PROMPT.format(
        source_path="s",
        folder_context="",
        existing_wiki_index="",
        source_text="",
        chunk_context="",
        knowledge_types=knowledge_types,
    )
    # The type segment must carry all 8 KnowledgeType values.
    assert f'"type": "{knowledge_types}"' in rendered
    assert f"one of {knowledge_types}" in rendered
    assert set(knowledge_types.split("|")) == {t.value for t in KnowledgeType}
    assert len(knowledge_types.split("|")) == 8
