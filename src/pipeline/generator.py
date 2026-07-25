"""Step 2: LLM renders wiki pages from AnalysisResult."""
import logging
from typing import Optional

from ..lib.budgeted import BudgetedLLM
from ..utils.slugify import slugify as _slugify
from ..wiki.core.paths import WikiPaths
from ..wiki.features.relations import parse_relations_from_response
from ..wiki.core.types import PageType, WikiPage
from ._pipeline_common import parse_llm_json
from .schemas import AnalysisResult
from .wiki_rules_prompt import WIKI_RULES_SUMMARY


_logger = logging.getLogger(__name__)


def _parse_llm_response(llm_resp) -> dict:
    """Normalise provider output to a dict (LLMResponse.content -> JSON).

    Delegates to ``_pipeline_common.parse_llm_json`` for the lenient
    parsing that handles markdown-fenced or prose-prefixed JSON when the
    LLM does not enforce a strict ``response_format``.
    """
    return parse_llm_json(llm_resp)


_logger = logging.getLogger(__name__)


GENERATOR_PROMPT = """You are rendering wiki pages for a knowledge base.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
title、body_markdown、relations[].context。Slugs (id、
relations[].target) 始终用 ASCII(中文术语用拼音或英文翻译)。

## Analysis result (from Step 1)
{analysis_json}

## Existing wiki index
{existing_wiki_index}

## Page Templates (use these to structure body_markdown)
Match the section headings exactly. Fill each `<!-- slot:NAME -->` with
substantive content from the source. Do NOT add new `##` sections not
in the template. Do NOT omit `##` sections present in the template.

{PAGE_TEMPLATES}

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
        PAGE_TEMPLATES=_render_template_section(paths.root),
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
                            # Hard-enum constraint: invalid page types fail
                            # the schema (rather than silently slipping
                            # through ``PageType(p["type"])`` and being
                            # logged+dropped). Forces the LLM to pick one
                            # of the four documented types.
                            "type": {
                                "type": "string",
                                "enum": ["source", "entity", "concept", "synthesis"],
                            },
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

    # Fix C: preserve the analyzer's page-type classification.
    # The analyzer prompt asks the LLM to pick one of {source, entity,
    # concept, synthesis} per suggested_page, and the generator should
    # render Markdown for those — not reclassify. Building a slug → type
    # map from the analyzer's suggested_pages means we can override the
    # LLM's re-decision (which it currently tends to bias toward
    # ``concept`` for everything abstract).
    type_from_analyzer: dict[str, str] = {
        p.slug: p.type.value if hasattr(p.type, "value") else str(p.type)
        for p in analysis.suggested_pages
    }

    import time
    now = int(time.time() * 1000)
    pages = []
    for p in response.get("pages", []):
        raw_slug = p.get("id")
        # Normalize the LLM's slug through pypinyin so 创酷中文网 always
        # becomes the same canonical form regardless of how the LLM
        # happened to transliterate it on this run.
        slug = _slugify(raw_slug) or raw_slug
        # Prefer the analyzer's classification when we have a matching slug.
        # The analyzer's map is keyed by the LLM's *original* slug, so look
        # up by the raw value too (in case analyzer's slug was different).
        raw_type = (
            type_from_analyzer.get(raw_slug)
            or type_from_analyzer.get(slug)
            or p.get("type")
        )
        try:
            page_type = PageType(raw_type)
        except ValueError:
            _logger.warning(
                f"Unknown page type for slug={slug!r}: {raw_type!r}; "
                "falling back to LLM's raw value"
            )
            try:
                page_type = PageType(p.get("type"))
            except ValueError:
                _logger.warning(f"Unknown page type: {p.get('type')}")
                continue
        pages.append(WikiPage(
            id=slug,
            title=p["title"],
            type=page_type,
            sources=[analysis.source_path],
            created_at=now,
            updated_at=now,
            body=p["body_markdown"],
            grade=p.get("grade", "B"),
            processing_depth=p.get("processing_depth", "concept"),
            is_immutable=p.get("is_immutable", False),
            relations=parse_relations_from_response(p.get("relations", [])),
        ))
    return pages


def _render_template_section(project_root) -> str:
    """Render the bundled templates as a prompt section.

    Falls back to a brief hint if no templates are available (e.g. running
    from a checkout where the bundled dir was pruned). The Generator
    should not silently lose this section — but it also should not crash
    the pipeline if the templates dir is missing.
    """
    from ..wiki.templates import list_available
    try:
        templates = list_available(project_root)
    except Exception as e:  # pragma: no cover
        _logger.warning("Could not load wiki page templates: %s", e)
        return "(no templates available)"

    if not templates:
        return "(no templates available)"

    parts: list[str] = []
    for tpl in templates:
        parts.append(f"### {tpl.type.value}")
        parts.append(tpl.body_markdown.strip())
        parts.append("")
    return "\n".join(parts).rstrip()
