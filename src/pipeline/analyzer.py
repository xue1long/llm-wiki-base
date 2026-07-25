"""Step 1: LLM extracts AnalysisResult from source text."""
import json
import logging
import re

from ..lib.budgeted import BudgetedLLM
from ._pipeline_common import parse_llm_json
from .schemas import AnalysisResult, ConceptMention, EntityMention, PageSpec


_logger = logging.getLogger(__name__)


ANALYZER_PROMPT = """You are analyzing a source document for a knowledge base.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
summary、key_facts、entities/concepts 的 name 和 context、
suggested_pages 的 title/reasoning/tags。Slugs 始终用 ASCII(中文
术语用拼音或英文翻译)。

## Context
- Source: {source_path}
- Folder: {folder_context}
- Existing wiki index:
{existing_wiki_index}

## Source text
{source_text}

## Task
Extract structured analysis. Output strict JSON:
{{
  "summary": "<1-2 sentence summary>",
  "key_facts": ["<fact 1>", ...],         // 3-7 facts
  "entities": [
    {{"name": "...", "slug": "...", "type": "person|org|concept|...", "context": "...", "confidence": 0.0-1.0}}
  ],
  "concepts": [
    {{"name": "...", "slug": "...", "context": "...", "confidence": 0.0-1.0}}
  ],
  "suggested_pages": [
    {{
      "type": "source|entity|concept|synthesis",
      "slug": "...",
      "title": "...",
      "reasoning": "...",
      "grade": "A|B|C",                    // optional; default B
      "processing_depth": "concept|memory", // optional; default concept
      "is_immutable": false,               // optional; default false
      "tags": ["genre/x", "func/y"]        // optional; default []
    }}
  ],
  "links_to_existing": ["<slug>"]          // existing wiki pages this references
}}
"""


async def analyze(
    source_text: str,
    source_ext: str,
    existing_wiki_index: str,
    folder_context: str,
    provider,
    task_id: str = "test",
    source_path: str = "raw/sources/test",
) -> AnalysisResult:
    """Step 1: LLM call -> AnalysisResult."""
    prompt = ANALYZER_PROMPT.format(
        source_path=source_path,
        folder_context=folder_context or "(none)",
        existing_wiki_index=existing_wiki_index or "(empty)",
        source_text=source_text,
    )

    async with BudgetedLLM(model="gpt-4o-mini", op="analyzer", provider=provider) as bl:
        llm_resp = await bl.call(
            prompt=prompt,
            response_format={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "key_facts": {"type": "array", "items": {"type": "string"}},
                    "entities": {"type": "array"},
                    "concepts": {"type": "array"},
                    "suggested_pages": {"type": "array"},
                    "links_to_existing": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "key_facts", "entities", "concepts", "suggested_pages", "links_to_existing"],
            },
        )

    response = _parse_llm_response(llm_resp)

    return AnalysisResult(
        task_id=task_id,
        source_path=source_path,
        summary=response.get("summary", ""),
        key_facts=response.get("key_facts", []),
        entities=[EntityMention(**e) for e in response.get("entities", [])],
        concepts=[ConceptMention(**c) for c in response.get("concepts", [])],
        suggested_pages=[PageSpec(**p) for p in response.get("suggested_pages", [])],
        links_to_existing=response.get("links_to_existing", []),
        folder_context=folder_context,
    )


def _parse_llm_response(llm_resp) -> dict:
    """Parse ``LLMResponse.content`` (or a raw dict/str from mocks/tests) as JSON.

    Delegates to ``_pipeline_common.parse_llm_json`` — kept as a thin
    wrapper so existing test imports continue to work and the analyzer
    can be located quickly by callers searching for ``_parse_llm_response``.
    """
    return parse_llm_json(llm_resp)