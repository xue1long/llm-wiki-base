"""Step 2: LLM renders wiki pages from AnalysisResult."""
import logging
from typing import Optional

from ..lib.budgeted import BudgetedLLM
from ..wiki.paths import WikiPaths
from ..wiki.relations import parse_relations_from_response
from ..wiki.types import PageType, WikiPage
from .schemas import AnalysisResult


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
      "frontmatter_extra": {{...}},        // optional extra frontmatter fields
      "body_markdown": "<markdown body, may use [[wikilinks]]>",
      "relations": [                      // optional cross-page relations
        {{"target": "<other-slug>", "type": "references|supports|causes|...",
          "weight": 0.0-1.0, "context": "<why>"}}
      ]
    }}
  ]
}}

Use [[other-slug]] for cross-references. frontmatter_extra may include tags, etc.
Relation types use the same vocabulary as the analysis (references, supports, causes, etc.).
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
    )

    response = await provider.complete(
        prompt=prompt,
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
                            "frontmatter_extra": {"type": "object"},
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

    import time
    now = int(time.time() * 1000)
    pages = []
    for p in response.get("pages", []):
        try:
            page_type = PageType(p["type"])
        except ValueError:
            _logger.warning(f"Unknown page type: {p['type']}")
            continue
        fm = p.get("frontmatter_extra", {})
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
