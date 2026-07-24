"""Step 2: LLM renders wiki pages from AnalysisResult."""
import logging
from typing import Optional

from ..lib.budgeted import BudgetedLLM
from ..wiki.core.paths import WikiPaths
from ..wiki.features.relations import parse_relations_from_response
from ..wiki.core.types import PageType, WikiPage
from .schemas import AnalysisResult
from .wiki_rules_prompt import WIKI_RULES_SUMMARY


_logger = logging.getLogger(__name__)


def _parse_llm_response(llm_resp) -> dict:
    """Normalise provider output to a dict (LLMResponse.content -> JSON).

    Legacy mock providers and unit tests pass dicts directly; production
    providers return an LLMResponse whose ``.content`` is a JSON string.
    Raises ``json.JSONDecodeError`` if the body is not valid JSON — falls
    through silently, never.
    """
    if isinstance(llm_resp, dict):
        return llm_resp
    content = getattr(llm_resp, "content", llm_resp)
    if not isinstance(content, str):
        content = str(content)
    import json
    return json.loads(content)


_logger = logging.getLogger(__name__)


GENERATOR_PROMPT = """You are rendering wiki pages for a knowledge base.

## Analysis result (from Step 1)
{analysis_json}

## Existing wiki index
{existing_wiki_index}

## Task
For each suggested page, render Markdown content. Output strict JSON:
{{
  "pages": [
    {{
      "id": "<slug>",
      "type": "source|entity|concept|synthesis",
      "title": "<title>",
      "body_markdown": "<markdown body, may use [[wikilinks]]>",
      "relations": [                      // optional cross-page relations
        {{"target": "<other-slug>", "type": "<one of the 17 built-in relation types below>",
          "weight": 0.0-1.0, "context": "<why>"}}
      ]
    }}
  ]
}}

Use [[other-slug]] for cross-references.

Built-in relation types (17): is_part_of, contains, references, referenced_by,
causes, caused_by, contradicts, supports, supported_by, supersedes, superseded_by,
depends_on, required_by, analogous_to, opposite_of, derived_from, derives.
You may also use `x-<name>` for any user-registered type. Do not invent
relation type names outside this set.

{WIKI_RULES_SUMMARY}
"""


async def generate(
    paths: WikiPaths,
    analysis: AnalysisResult,
    existing_wiki_index: str,
    provider,
    model: str = "gpt-4o-mini",
) -> list[WikiPage]:
    """Step 2: LLM call → list of WikiPage objects."""
    import json
    analysis_json = json.dumps({
        "summary": analysis.summary,
        "key_facts": analysis.key_facts,
        "entities": [e.to_dict() for e in analysis.entities],
        "concepts": [c.__dict__ for c in analysis.concepts],
        "suggested_pages": [p.__dict__ for p in analysis.suggested_pages],
        "links_to_existing": analysis.links_to_existing,
    }, ensure_ascii=False, indent=2)

    prompt = GENERATOR_PROMPT.format(
        analysis_json=analysis_json,
        existing_wiki_index=existing_wiki_index or "(empty)",
        WIKI_RULES_SUMMARY=WIKI_RULES_SUMMARY,
    )

    response = await provider.complete(
        messages=[{"role": "user", "content": prompt}],
        response_format={
            "type": "object",
            "properties": {
                "pages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string"},
                            "title": {"type": "string"},
                            "body_markdown": {"type": "string"},
                            "relations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "target": {"type": "string"},
                                        "type": {"type": "string"},
                                        "weight": {"type": "number"},
                                        "context": {"type": "string"},
                                    },
                                    "required": ["target", "type"],
                                },
                            },
                        },
                        "required": ["id", "type", "title", "body_markdown"],
                    },
                },
            },
            "required": ["pages"],
        },
    )
    response = _parse_llm_response(response)

    import time
    now = int(time.time() * 1000)
    pages = []
    for p in response.get("pages", []):
        try:
            page_type = PageType(p["type"])
        except ValueError:
            _logger.warning(f"Unknown page type: {p['type']}")
            continue
        pages.append(WikiPage(
            id=p["id"],
            title=p["title"],
            type=page_type,
            sources=[analysis.source_path],
            created_at=now,
            updated_at=now,
            body=p["body_markdown"],
            relations=parse_relations_from_response(p.get("relations", [])),
        ))
    return pages
