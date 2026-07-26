"""Step 2: LLM renders wiki pages from AnalysisResult.

Plan 27 (2026-07-26 wiki v2.3 schema) changes:

- The JSON response is a structured ``slots`` object (slot name → content)
  rather than an opaque ``body_markdown`` string.
- The schema enforces ``slots`` presence and minLength on each slot value;
  the per-PageType required slots are validated in code (because provider
  JSON-schema implementations don't uniformly support ``oneOf``).
- The prompt no longer tells the LLM it can OMIT sections.
- A retry loop nudges the LLM once when required slots are missing; if it
  still fails after one retry, the Generator fills them with a clearly
  marked placeholder and emits a WARN log line so operators can spot the
  fallback at a glance.

This module is the single source of truth for wiki template enforcement.
See docs/superpowers/plans/2026-07-26-wiki-schema-v23.md.
"""
import logging
from pathlib import Path
from typing import Optional

from ..lib.budgeted import BudgetedLLM
from ..utils.slugify import slugify as _slugify
from ..wiki.core.paths import WikiPaths
from ..wiki.features.relations import parse_relations_from_response
from ..wiki.core.types import PageType, WikiPage
from ..wiki.templates import (
    Template,
    compute_slot_fill_status,
    list_resolved,
    render_body,
    required_slot_names,
)
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

Do NOT output chain-of-thought, hidden reasoning, or a thinking
transcript. Reason internally and emit only the requested JSON.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
title、body_markdown、relations[].context。Slugs (id、
relations[].target) 可直接使用中文 (CJK),也可使用 ASCII kebab-case —
保留概念的自然字面,无需拼音转写;专有名词/英文术语在 ASCII 段仍
保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。

## Analysis result (from Step 1)
{analysis_json}

## Existing wiki index
{existing_wiki_index}

## Source page ids for this run (Fix B — deterministic source-page slugs)
Source-page ids are derived deterministically from the raw file path
(NFC-normalised stem + 8-hex md5 hash of the full path). They are NOT
chosen by you. Use the EXACT slugs below whenever a ``[[wikilink]]``
references the corresponding source page; do NOT invent variants like
dropping interior hyphens or collapsing segments — every variantion
produces a broken link that no on-disk file satisfies.

{SOURCE_SLUG_MAP}

## Slug Reuse (CRITICAL — prevent wikilink drift across ingests)
The `## Existing wiki index` above lists every page currently in the
wiki by its exact `id` slug. Whenever your body_markdown refers to a
concept via `[[wikilinks]]`, or `relations[].target` references a
slugs, you MUST reuse the EXISTING slug verbatim — copy it character-
for-character. Do not invent new pinyin transliterations, do not
shorten or lengthen, do not switch between English and pinyin
renderings, do not introduce new slug variants. If a concept already
has a page (e.g. `qi-dai-gan-chuangzuo`), use that exact slug even
when your analysis would naturally shorten it (e.g. to `qi-dai-gan`).
Reusing keeps cross-references resolvable across multiple ingests;
inventing creates broken `[[...]]` links the reader cannot follow.

## Page Templates (use these to structure `slots`)
Each page type has a fixed set of `slots` you must fill. Templates are
listed below under `{PAGE_TEMPLATES}`. For every `<!-- slot:NAME -->`
slot, return a substantive string (or list of strings) named `slots.NAME`.
Required slots are unmarked; slots marked `_(optional)_` may be omitted
or returned as an empty list when the source has no relevant content —
**only for those**, not for unmarked required ones.

Strict rules — schema is enforced:
- Every `<!-- slot:NAME -->` (no `?`) is required. NEVER use "..." /
  "（空）" / "（待补充）" / "placeholder" / "TBD" or similar filler as a
  body or slot value — the validator will REJECT the response and a
  retry is triggered. Provide substantive content, or write a short
  note explaining what the source did/n't say (e.g. "无相关引用").
- Do NOT add new slot names not in the template. The schema rejects
  extra keys under `slots`.
- Optional slots (`<!-- slot:NAME? -->` / `<!-- if:X -->`): only OMIT
  when you have nothing to put; either omit the property entirely or
  return `[]`. The whole section is dropped from the rendered body when
  the slot is empty.
- Each slot value must be ≥ 1 character after trim. For lists, at least
  one item with substantive content.

Good slot content:
- 1-3 sentences or a list of 1-3 short bullets summarising what the
  source says about that aspect of the topic.
- May include `[[wikilinks]]` to other slugs in the existing index.

{PAGE_TEMPLATES}

## Subject boundary (do not transfer claims across entities)
When the source discusses multiple entities / models / products /
methods / works / characters, keep each claim, evaluation, limitation,
benchmark result, and recommendation attached to the exact subject it
describes. Do NOT transfer a claim about one subject onto another
subject's page just because they share terms (names, features,
keywords, time periods, or the same source). If a page must reference
another subject for comparison, write it explicitly as a comparison
and cite the source that supports it.

## Task
For each suggested page, fill its slots. Output strict JSON:
{{
  "pages": [
    {{
      "id": "<slug>",
      "type": "source|entity|concept|synthesis",
      "title": "<title>",
      "slots": {{
        "<slot_name>": "<content>",            // or a list of strings
        "...": "..."
      }},
      "relations": [                          // optional cross-page relations
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

## Language (re-asserted — applies to ALL output below)
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
title、slots[*]、relations[].context。Slugs (id、
relations[].target) 可直接使用中文 (CJK),也可使用 ASCII kebab-case —
保留概念的自然字面,无需拼音转写。
"""


async def generate(
    paths: WikiPaths,
    analysis: AnalysisResult,
    existing_wiki_index: str,
    provider,
    model: str = "gpt-4o-mini",
    source_slug_map: Optional["dict[str, str]"] = None,
) -> list[WikiPage]:
    """Step 2: LLM call → list of WikiPage objects.

    Plan 27 (2026-07-26 wiki v2.3 schema): the LLM now returns a
    structured ``slots`` object per page. The schema enforces that
    ``slots`` exists and each value is a non-empty string; per-PageType
    required slot names are validated in code (because provider JSON
    schemas don't uniformly support ``oneOf``). A retry loop nudges the
    LLM once when required slots are missing; persistent gaps are filled
    with a placeholder and logged as WARN.

    ``source_slug_map``: ``{raw_path_str: source_page_slug}``. Each
    value is what ingest.py computed for the ``source`` page this run
    using ``{NFC stem}-{md5(path)[:8]}`` (Fix B). When provided, the
    slug map is rendered into the prompt so the LLM does NOT have to
    guess source-page ids when emitting ``[[wikilinks]]``. Source pages
    ingested in earlier runs already appear in the wiki index and
    don't need to be listed here.
    """
    import json, time

    # 0. Resolve the 4 active templates for this project (bundled /
    #    user-global / project-local in priority order). Mapping needed
    #    both for the schema-required check and for rendering.
    resolved_templates = {t.type: t for t in list_resolved(paths.root)}
    required_slots_by_type: dict[PageType, list[str]] = {
        pt: required_slot_names(resolved_templates[pt])
        for pt in PageType
        if pt in resolved_templates
    }

    analysis_json = json.dumps({
        "summary": analysis.summary,
        "key_facts": analysis.key_facts,
        "entities": [e.to_dict() for e in analysis.entities],
        "concepts": [c.__dict__ for c in analysis.concepts],
        "suggested_pages": [p.__dict__ for p in analysis.suggested_pages],
        "links_to_existing": analysis.links_to_existing,
    }, ensure_ascii=False, indent=2)

    # JSON schema for the LLM response. The hard enum on `type` already
    # forces a valid PageType. The `slots` constraint is generic — we
    # only check minLength on each value at the provider level; the
    # per-PageType required slot names are checked below in code.
    response_format = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["source", "entity", "concept", "synthesis"],
                        },
                        "title": {"type": "string"},
                        "slots": {
                            "type": "object",
                            "additionalProperties": {
                                # Each slot value: non-empty string, OR a list
                                # where every element is a non-empty string.
                                # Providers commonly accept {"type": "string", "minLength": 1}
                                # uniformly; list-shape is normalised in code.
                                "type": "string",
                                "minLength": 1,
                            },
                            "minProperties": 1,
                        },
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
                    "required": ["id", "type", "title", "slots"],
                },
            },
        },
        "required": ["pages"],
    }

    # 1. Initial LLM call + parse.
    base_prompt = GENERATOR_PROMPT.format(
        analysis_json=analysis_json,
        existing_wiki_index=existing_wiki_index or "(empty)",
        WIKI_RULES_SUMMARY=WIKI_RULES_SUMMARY,
        PAGE_TEMPLATES=_render_template_section(paths.root),
        SOURCE_SLUG_MAP=_format_source_slug_map(source_slug_map),
    )

    response_dict = await _call_with_slot_retry(
        provider=provider,
        base_prompt=base_prompt,
        response_format=response_format,
        required_slots_by_type=required_slots_by_type,
    )

    # 2. If after retry some required slots are still missing, fill them
    #    with a clearly marked placeholder so every rendered page is
    #    structurally complete (every required heading has at least the
    #    placeholder line). Operators will see the WARN in the log.
    filled_pages, missing_summary = _ensure_required_slots_filled(
        response_dict.get("pages", []),
        required_slots_by_type=required_slots_by_type,
    )
    if missing_summary:
        _logger.warning(
            "[generator] required slots still missing after retry, "
            "filled with placeholder: %s",
            missing_summary,
        )

    # 3. Build WikiPage objects. Use the resolved templates to render
    #    body markdown from slots via the section-aware renderer.
    type_from_analyzer: dict[str, str] = {
        p.slug: p.type.value if hasattr(p.type, "value") else str(p.type)
        for p in analysis.suggested_pages
    }

    now = int(time.time() * 1000)
    pages: list[WikiPage] = []
    for p in filled_pages:
        raw_slug = p.get("id")
        slug = _slugify(raw_slug) or raw_slug
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

        # Enforce deterministic source-page slug: the source_slug_map is
        # guaranteed correct ({stem}-{md5[:8]}), while the LLM may emit
        # pinyin or hallucinate a slug from a different source (2026-07-26).
        if source_slug_map and page_type == PageType.SOURCE:
            map_slug = source_slug_map.get(analysis.source_path)
            if map_slug:
                slug = map_slug

        template = resolved_templates.get(page_type)
        if template is None:
            # No template for this page type — accept whatever body the
            # LLM returned (rare; should not occur for normal ingests).
            body_md = ""
        else:
            body_md = render_body(
                template_body=template.body_markdown,
                slots=p.get("slots", {}) or {},
                page_type=page_type,
                template_version=template.version or "",
            )

        pages.append(WikiPage(
            id=slug,
            title=p["title"],
            type=page_type,
            sources=[analysis.source_path],
            created_at=now,
            updated_at=now,
            body=body_md,
            grade=p.get("grade", "B"),
            processing_depth=p.get("processing_depth", "concept"),
            is_immutable=p.get("is_immutable", False),
            relations=parse_relations_from_response(p.get("relations", [])),
        ))
    return pages


# ---------------------------------------------------------------------------
# Internal helpers for v2.3 slot enforcement.
# ---------------------------------------------------------------------------


async def _call_with_slot_retry(
    *,
    provider,
    base_prompt: str,
    response_format: dict,
    required_slots_by_type: dict[PageType, list[str]],
) -> dict:
    """Call the LLM, retry once if any required slot is missing.

    Returns the parsed response dict (with ``pages`` key).
    """
    MAX_GEN_ATTEMPTS = 2  # initial + 1 retry
    last_missing: dict[str, list[str]] = {}
    last_response: dict = {}

    for attempt in range(MAX_GEN_ATTEMPTS):
        extra = ""
        if attempt > 0 and last_missing:
            lines = [
                "## Retry — your previous response was missing these required slots:",
            ]
            for ptype_name, names in last_missing.items():
                lines.append(f"- {ptype_name}: {', '.join(names)}")
            lines.append(
                "Please provide substantive content for each one. "
                "Empty strings, '...', '（空）', '（待补充）', 'placeholder', "
                "'TBD' etc. all FAIL the validator again."
            )
            extra = "\n\n" + "\n".join(lines) + "\n"

        response = await provider.complete(
            messages=[{"role": "user", "content": base_prompt + extra}],
            response_format=response_format,
        )
        response_dict = _parse_llm_response(response)
        last_response = response_dict

        last_missing = _find_missing_required_slots(
            response_dict.get("pages", []),
            required_slots_by_type=required_slots_by_type,
        )
        if not last_missing:
            return response_dict

    return last_response


def _find_missing_required_slots(
    pages: list[dict],
    *,
    required_slots_by_type: dict[PageType, list[str]],
) -> dict[str, list[str]]:
    """Return ``{PageType.value: [slot_name, ...]}`` for missing required slots."""
    missing_by_type: dict[str, list[str]] = {}
    for p in pages:
        try:
            ptype = PageType(p.get("type"))
        except (ValueError, TypeError):
            continue
        required = required_slots_by_type.get(ptype, [])
        if not required:
            continue
        status = compute_slot_fill_status(p.get("slots", {}) or {}, required)
        if status.missing:
            missing_by_type[ptype.value] = status.missing
    return missing_by_type


def _ensure_required_slots_filled(
    pages: list[dict],
    *,
    required_slots_by_type: dict[PageType, list[str]],
    placeholder: str = "（系统占位：此项由系统补齐，请人工补充）",
) -> tuple[list[dict], dict[str, list[str]]]:
    """Fill any still-missing required slots with a placeholder.

    Returns (mutated pages, summary of what was filled).
    """
    summary: dict[str, list[str]] = {}
    for p in pages:
        try:
            ptype = PageType(p.get("type"))
        except (ValueError, TypeError):
            continue
        required = required_slots_by_type.get(ptype, [])
        if not required:
            continue
        slots = p.setdefault("slots", {})
        for name in required:
            value = slots.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                slots[name] = placeholder
                summary.setdefault(ptype.value, []).append(name)
    return pages, summary


def _render_template_section(project_root: Path) -> str:
    """Render the bundled templates as a prompt section.

    Falls back to a brief hint if no templates are available (e.g. running
    from a checkout where the bundled dir was pruned). The Generator
    should not silently lose this section — but it also should not crash
    the pipeline if the templates dir is missing.

    Re-parses each template's body_markdown into an AST and uses
    ``render_for_prompt`` to produce a compact, LLM-facing skeleton
    (headings + slot markers, optional slots annotated). The previous
    implementation dumped raw ``tpl.body_markdown`` directly into the
    prompt, which kept every blank line and added no hint about which
    sections were optional.
    """
    from ..wiki.templates import list_resolved
    from ..wiki.templates.parser import parse, render_for_prompt, TemplateParseError

    try:
        templates = list_resolved(project_root)
    except Exception as e:  # pragma: no cover
        _logger.warning("Could not load wiki page templates: %s", e)
        return "(no templates available)"

    if not templates:
        return "(no templates available)"

    parts: list[str] = []
    for tpl in templates:
        parts.append(f"### {tpl.type.value}")
        try:
            ast = parse(tpl.body_markdown, expected_type=tpl.type)
            parts.append(render_for_prompt(ast))
        except TemplateParseError as e:
            # If we can't parse the resolved template (shouldn't happen
            # since resolve() already validated the type header), fall
            # back to the raw body rather than dropping the section.
            _logger.warning(
                "Could not re-parse template %s for prompt injection: %s",
                tpl.path, e,
            )
            parts.append(tpl.body_markdown.strip())
        parts.append("")
    return "\n".join(parts).rstrip()


def _format_source_slug_map(
    source_slug_map: Optional[dict],
) -> str:
    """Render the ``{SOURCE_SLUG_MAP}`` prompt section.

    Lists every source-page slug created by THIS ingest run. Source
    pages from earlier runs are already visible in the wiki index
    included earlier in the prompt — only newly-produced slugs need
    to be listed explicitly.

    Without this section the LLM has to guess what slug a freshly-
    produced source page will have on disk. Plan 27 + Plan v2.4
    made the slug deterministic (``{NFC stem}-{md5(path)[:8]}``),
    but the LLM doesn't redo that math; if its guess diverges from
    the on-disk name, every [[wikilink]] to that source page is
    broken. This listing eliminates the guess.
    """
    if not source_slug_map:
        return "(no source pages produced by this run)"
    lines = ["```"]
    for raw_path, slug in source_slug_map.items():
        raw_name = Path(raw_path).name if raw_path else "?"
        lines.append(f"  - raw:  {raw_name}\n    slug: {slug}")
    lines.append("```")
    return "\n".join(lines)