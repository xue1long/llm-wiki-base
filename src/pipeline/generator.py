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
import re
from pathlib import Path
from typing import Optional

from ..lib.budgeted import BudgetedLLM
from ..utils.path import normalize_source_path
from ..utils.slugify import slugify as _slugify
from ..wiki.core.paths import WikiPaths
from ..wiki.features.relations import parse_relations_from_response
from ..wiki.features.tag_namespace import is_valid as is_valid_tag
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

# Truncate very large sources to keep prompt size manageable and
# prevent page-count explosion (observed: 34K source → 83 pages).
# Reduced to 8000 for CPU Ollama — larger prompts time out at 180s.
MAX_SOURCE_CHARS = 8000


def _parse_llm_response(llm_resp) -> dict:
    """Normalise provider output to a dict (LLMResponse.content -> JSON).

    Delegates to ``_pipeline_common.parse_llm_json`` for the lenient
    parsing that handles markdown-fenced or prose-prefixed JSON when the
    LLM does not enforce a strict ``response_format``.
    """
    return parse_llm_json(llm_resp)


_DEPTH_BY_TYPE: dict[PageType, str] = {
    PageType.SOURCE: "source",
    PageType.ENTITY: "entity",
    PageType.CONCEPT: "concept",
    PageType.SYNTHESIS: "synthesis",
}


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

Strict rules — schema is enforced. Empty slots = retry = wasted tokens.
- Every `<!-- slot:NAME -->` (no `?`) is REQUIRED. NEVER use "..." /
  "（空）" / "（待补充）" / "placeholder" / "TBD" or similar filler —
  the validator REJECTS empty values and triggers a retry.
- Provide substantive content, or use the fallback for that slot (see below).
- Do NOT add new slot names not in the template. The schema rejects
  extra keys under `slots`.
- Optional slots (`<!-- slot:NAME? -->` / `<!-- if:X -->`): only OMIT
  when you have nothing to put; either omit the property entirely or
  return `[]`.
- Each slot value must be ≥ 1 character after trim. Lists: ≥ 1 substantive item.

Slot minimums and fallbacks (DO NOT leave these required slots empty):
  `references`           → At LEAST `- [[<source-page-slug>]]`
  `source_meta`          → MUST state source URL/platform + date
  `related_concepts`     → At LEAST 2 `[[wikilinks]]` to other pages
  `related`              → At LEAST 1 `[[wikilink]]`
  `key_points`           → At LEAST 3 bullets from source
  `extracted_concepts`   → At LEAST 3 `[[wikilinks]]`
  `examples`             → If none: "来源未提供具体例子"
  `comparison_dimensions`→ At LEAST 2 dimensions
  `overview`             → At LEAST 1 paragraph

When source truly lacks info for a required slot, write "来源未详述此方面"
— NEVER leave it empty or filled with placeholder text.

{PAGE_TEMPLATES}

## Entity pages are REQUIRED
Every entity listed in `suggested_pages` (type=entity) MUST have a
corresponding entry in your `pages` output. The wiki knowledge graph
depends on entity pages existing — without them, cross-references
break and the graph is unnavigable. If the source has limited info
about an entity, fill the slots with what IS available, note the gaps
briefly (e.g. "来源未详述此概念"), and assign grade=C. Do NOT skip
entity pages just because they're not "interesting" concept/synthesis
material. Every missing entity page creates a broken link chain.

## Subject boundary (do not transfer claims across entities)
When the source discusses multiple entities / models / products /
methods / works / characters, keep each claim, evaluation, limitation,
benchmark result, and recommendation attached to the exact subject it
describes. Do NOT transfer a claim about one subject onto another
subject's page just because they share terms (names, features,
keywords, time periods, or the same source). If a page must reference
another subject for comparison, write it explicitly as a comparison
and cite the source that supports it.

## Factuality (no invented examples)
Only use examples, titles, names, and data points that appear in the
source text. Do NOT invent plausible-sounding book titles, author
quotes, statistics, or case studies from your training data. If the
source mentions only one example for a concept, list exactly that one
— do not pad with 2-3 extra "representative" examples you guessed.
When the source gives no examples for a subject, write "来源未提供例子"
rather than fabricating one.

## Reference sections must use wikilinks
The "参考来源" / "references" slot in every template is meant to
contain navigable `[[wikilinks]]`, not plain text. Always use the
exact slug from the `## Source page ids` listing above for source
pages. For cross-references to other wiki pages, use the slug
listed in `## Existing wiki index`.  Example:
  GOOD: - [[必备资料11月28号创酷中文网女频现言讲课记录_8c363e-a1b2c3d4]]
  BAD:  - 《必备资料11月28号创酷中文网女频现言讲课记录》

## Tags guidance (受控命名空间)
每个输出页可带 0-N 个 `tags` (分类检索用). 每个 tag 必须是 `前缀/名称` 形式, 前缀
只能是以下 8 个受控值之一 (名称用中文或英文, 不要含空格):
- genre/       题材类型   (如 genre/现言, genre/玄幻)
- func/        功能类型   (如 func/教程, func/案例)
- char/        角色类型   (如 char/总裁, char/女主)
- event/       事件类型   (如 event/签约, event/冲突)
- mood/        情绪氛围   (如 mood/甜宠, mood/悬疑)
- entity/      是什么(What) (如 entity/创酷中文网, entity/起点)
- scene_phase/ 何时用(When) (如 scene_phase/开篇, scene_phase/高潮)
- status/      生命周期   (如 status/草稿, status/完结)
不要使用这 8 个以外的前缀, 也不要写裸标签(无 `/`). 来源/概念页至少给 1-2 个最贴切的 tag.
(若本页在分析阶段已给出 tags 建议, 你可直接沿用或按其内容调整.)

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
      ],
      "tags": ["genre/现言", "func/教程"]     // optional; 受控命名空间前缀 (见 Tags guidance)
      "category": "",                          // optional; 一级分类
      "taxonomy_sub": "",                      // optional; 二级分类
      "processing_depth": "concept"            // optional; concept|memory
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
保留概念的自然字面,无需拼音转写;专有名词/英文术语在 ASCII 段仍
保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。
"""


# ---------------------------------------------------------------------------
# Unified prompt — merges Analyzer + Generator into a single LLM call.
# Latency drops ~50 % (one call instead of two); quality may improve
# because the model sees the full task context at once (no intermediate
# JSON to lose entities, slug mismatches, or hallucinated examples).
# ---------------------------------------------------------------------------

UNIFIED_PROMPT = """You are a knowledge-base engine. Read the source text,
extract structured knowledge, and render wiki pages in ONE pass.

## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no
   introductory text, no concluding remarks.
2. Your response MUST start with `{{` and end with `}}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

## Source
- Path: {source_path}
- Folder: {folder_context}
- Text:
{source_text}

## Existing wiki index (reuse slugs exactly as listed)
{existing_wiki_index}

## Source page id for THIS run
{SOURCE_SLUG_MAP}

## Page Templates
{PAGE_TEMPLATES}

## Rules (all mandatory)

**Page budget**: 5-15 pages total. For short sources (<2000 chars), aim for 5-8.
Focus on the most important entities and concepts — quality over quantity.
Every page must have substantive content.
**MINIMUM**: Always generate at least 1 source page + 2 entity/concept pages.
Even if the source is short or seemingly off-topic, extract what you can —
empty extractions are worse than thin pages.
**At least one entity page is REQUIRED** for every source document, regardless
of length. A source with zero downstream pages is a pipeline failure.

**Language**: 简体中文 for all user-visible text (title, slots, relations[].context).
Slugs may be CJK or ASCII kebab-case — keep the concept's natural form, no forced pinyin.

**Slug reuse**: Use EXISTING slugs from the wiki index verbatim. Never invent variants.

**Slot filling — CRITICAL: NO EMPTY SLOTS ALLOWED**:
- Every `<!-- slot:NAME -->` (no `?`) is REQUIRED and MUST have substantive content.
  An empty or placeholder-filled slot triggers retry and wastes tokens for everyone.
- Never use placeholder text ("...", "（空）", "TBD", "placeholder", "（系统占位...）").
- Optional slots (`<!-- slot:NAME? -->`): omit when empty.
- Each slot: ≥ 1 char after trim. Lists: ≥ 1 substantive item.

**Slot-specific minimums (enforced — do NOT leave these empty)**:
SLOT                  | PAGE TYPE   | MINIMUM ACCEPTABLE CONTENT
----------------------|-------------|----------------------------------------------------
`references`          | concept     | At LEAST one `[[wikilink]]` to the source page
`source_meta`         | source      | MUST include: 来源(URL/平台), 下载时间, 发布组织
`related_concepts`    | concept     | At LEAST 2 `[[wikilinks]]` to other concept/entity pages
`related`             | entity      | At LEAST 1 `[[wikilink]]` to the source page or parent entity
`key_points`          | source      | At LEAST 3 bullet points from the source text
`extracted_concepts`  | source      | At LEAST 3 `[[wikilinks]]` to concept/entity pages generated below
`comparison_dimensions`| synthesis  | At LEAST 2 dimensions being compared
`overview`            | synthesis   | At LEAST 1 paragraph summarising the comparison

**FALLBACKS — when source truly lacks info, use these instead of empty/placeholder**:
- `references` → Write `- [[<source-page-slug>]]` (the slug from `## Source page id` above)
- `source_meta` → Write "来源: [文件名]; 格式: Markdown; 下载时间: 见原始文件头部"
- `related_concepts` → List the concept/entity slugs you defined in other pages of THIS response
- `related` → Write `- [[<source-page-slug>]]`
- `examples` → Write "来源未提供具体例子" (invent NOTHING)
- ALL OTHERS → Write "来源未详述此方面" (not empty, not placeholder)

**Entity pages are REQUIRED**: Every meaningful entity (person, org, work, platform,
genre) mentioned in the source MUST have a page. Missing entities create broken
links. If the source has limited detail, write what IS available and grade=C.

**Factuality**: Only use examples/titles/names from the source text. Do NOT invent
plausible-sounding book titles, author quotes, or statistics. When no example
exists, write "来源未提供例子".

**Reference sections**: Use `[[exact-slug]]` wikilinks, not plain text.
GOOD: `- [[必备资料11月28号创酷中文网女频现言讲课记录_8c363e-a1b2c3d4]]`
BAD:  `- 《必备资料11月28号创酷中文网女频现言讲课记录》`

**Wikilinks in JSON arrays**: When a slot value is a JSON array (e.g. `"references"`,
`"related_concepts"`, `"related"`, `"aliases"`, `"examples"`, `"characteristics"`,
`"key_points"`, `"extracted_concepts"`), every wikilink MUST be wrapped in
double-quotes so it is a valid JSON string:
GOOD: `"references": ["[[slug-one]]", "[[slug-two]]"]`
BAD:  `"references": [[[slug-one]], [[slug-two]]]`   ← broken JSON, will be rejected!

If you forget the quotes around `[[wikilinks]]` in an array, the entire response
will fail to parse and a slower fallback pipeline runs instead.

**Subject boundary**: Keep claims attached to their exact subject. Do NOT
transfer a claim about one entity to another just because they share terms.

**Tags**: `prefix/name` format, 8 allowed prefixes:
genre/ func/ char/ event/ mood/ entity/ scene_phase/ status/

**Relation types** (17 built-in + `x-*` custom):
is_part_of contains references referenced_by causes caused_by contradicts
supports supported_by supersedes superseded_by depends_on required_by
analogous_to opposite_of derived_from derives

{WIKI_RULES_SUMMARY}

## Task
Read the source text. Identify entities, concepts, key facts, and synthesize
knowledge into structured wiki pages. Output strict JSON:

{{
  "pages": [
    {{
      "id": "<slug>",
      "type": "source|entity|concept|synthesis",
      "title": "<中文标题>",
      "slots": {{"<slot_name>": "<content or list of strings>"}},
      "relations": [{{"target": "<slug>", "type": "<relation_type>", "weight": 0.0-1.0, "context": "<why>"}}],
      "tags": ["genre/现言", "func/教程"],
      "grade": "A|B|C",
      "category": "",
      "taxonomy_sub": "",
      "processing_depth": "concept|memory"
    }}
  ]
}}

Every slot in the template for each page type MUST be filled.
Use [[other-slug]] for cross-references within slot content.
"""


async def unified_generate(
    source_text: str,
    source_path: str,
    folder_context: str,
    paths: WikiPaths,
    existing_wiki_index: str,
    provider,
    source_slug_map: Optional["dict[str, str]"] = None,
) -> list[WikiPage]:
    """Single-pass: analyze source text + render wiki pages in one LLM call.

    Replaces the two-step Analyze→Generate pipeline.  Latency drops ~50 %;
    quality may improve because the model reads the full source in one
    context window (no intermediate JSON to drop entities or mangle slugs).
    """
    import json as _json
    import time as _time
    import re as _re

    _truncated = False
    if len(source_text) > MAX_SOURCE_CHARS:
        source_text = source_text[:MAX_SOURCE_CHARS] + "\n\n[... 文本过长，已截断 ...]"
        _truncated = True

    _logger.info(
        "[unified_generate] single-pass ingest for %s (%d chars%s)",
        source_path, len(source_text),
        ", truncated" if _truncated else "",
    )

    # Resolve templates (same as `generate()`).
    resolved_templates = {t.type: t for t in list_resolved(paths.root)}
    required_slots_by_type: dict[PageType, list[str]] = {
        pt: required_slot_names(resolved_templates[pt])
        for pt in PageType
        if pt in resolved_templates
    }

    response_format = {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": ["source", "entity", "concept", "synthesis"]},
                        "title": {"type": "string"},
                        "slots": {
                            "type": "object",
                            "additionalProperties": {"type": "string", "minLength": 1},
                            "minProperties": 1,
                        },
                        "relations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "target": {"type": "string"}, "type": {"type": "string"},
                                    "weight": {"type": "number"}, "context": {"type": "string"},
                                },
                                "required": ["target", "type"],
                            },
                        },
                        "tags": {"type": "array", "items": {"type": "string", "minLength": 1}},
                        "grade": {"type": "string", "enum": ["A", "B", "C"]},
                        "category": {"type": "string"},
                        "taxonomy_sub": {"type": "string"},
                        "processing_depth": {"type": "string", "enum": ["concept", "memory"]},
                    },
                    "required": ["id", "type", "title", "slots"],
                },
            },
        },
        "required": ["pages"],
    }

    base_prompt = UNIFIED_PROMPT.format(
        source_path=source_path,
        folder_context=folder_context or "(none)",
        source_text=source_text,
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
        timeout=600.0,
    )

    raw_pages = response_dict.get("pages", [])

    # Deterministic auto-fill BEFORE placeholder — fills trivially
    # extractable slots (references, source_meta, related_concepts, etc.)
    # without relying on LLM. Reduces placeholder rate significantly.
    raw_pages = _auto_fill_deterministic_slots(
        raw_pages,
        source_path=source_path,
        source_text=source_text,
        source_slug_map=source_slug_map,
    )

    filled_pages, missing_summary = _ensure_required_slots_filled(
        raw_pages,
        required_slots_by_type=required_slots_by_type,
    )
    if missing_summary:
        _logger.warning(
            "[unified_generate] required slots still missing after retry+auto-fill, "
            "filled with placeholder: %s", missing_summary,
        )

    now = int(_time.time() * 1000)
    pages: list[WikiPage] = []
    _source_title_to_slug: dict[str, str] = {}
    if source_slug_map:
        for raw_path, sl in source_slug_map.items():
            _stem = Path(raw_path).stem if raw_path else ""
            if _stem:
                _source_title_to_slug[_stem] = sl

    for p in filled_pages:
        title = p.get("title", "")
        slug = _slugify(title) or p.get("id", "")
        try:
            page_type = PageType(p.get("type"))
        except ValueError:
            _logger.warning(f"Unknown page type: {p.get('type')}")
            continue

        # Deterministic source-page slug
        if source_slug_map and page_type == PageType.SOURCE:
            map_slug = source_slug_map.get(source_path)
            if map_slug:
                slug = map_slug

        template = resolved_templates.get(page_type)
        if template is None:
            body_md = ""
        else:
            body_md = render_body(
                template_body=template.body_markdown,
                slots=p.get("slots", {}) or {},
                page_type=page_type,
                template_version=template.version or "",
            )

        # Fix broken source-page wikilinks in rendered body
        if source_slug_map and body_md:
            _known_source_slugs: set[str] = set(source_slug_map.values())
            def _replace_broken_wl(m):
                target = m.group(1).split("|")[0].split("#")[0].strip()
                canon = _slugify(target) or target
                for real_slug in _known_source_slugs:
                    if (_slugify(real_slug) or real_slug) == canon:
                        alias = m.group(1)[len(target):]
                        return f"[[{real_slug}{alias}]]"
                return m.group(0)
            body_md = _re.sub(r"\[\[(.*?)\]\]", _replace_broken_wl, body_md)

        # Relation dedup by slugified target
        raw_relations = p.get("relations", []) or []
        deduped_relations: list[dict] = []
        seen_targets: set = set()
        for rel in sorted(raw_relations, key=lambda r: r.get("weight", 1.0), reverse=True):
            tgt = rel.get("target", "")
            if not tgt:
                continue
            canon = _slugify(tgt) or tgt
            if canon not in seen_targets:
                seen_targets.add(canon)
                deduped_relations.append(rel)

        pages.append(WikiPage(
            id=slug, title=p["title"], type=page_type,
            sources=[normalize_source_path(source_path, paths.root)],
            created_at=now, updated_at=now, body=body_md,
            grade=p.get("grade", "B"),
            processing_depth=p.get("processing_depth") or _DEPTH_BY_TYPE.get(page_type, "concept"),
            is_immutable=p.get("is_immutable", False),
            relations=parse_relations_from_response(deduped_relations),
            tags=_resolve_page_tags_unified(p),
            category=p.get("category", ""),
            taxonomy_sub=p.get("taxonomy_sub", ""),
        ))
    return pages


def _resolve_page_tags_unified(page: dict) -> list[str]:
    """Resolve tags for the unified path (no analyzer fallback)."""
    raw = page.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [t for t in raw if isinstance(t, str) and is_valid_tag(t)]


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
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "description": "controlled-namespace tags, each 'prefix/name' with prefix in {genre,func,char,event,mood,entity,scene_phase,status}",
                        },
                        "category": {"type": "string"},
                        "taxonomy_sub": {"type": "string"},
                        "processing_depth": {"type": "string", "enum": ["concept", "memory"]},
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
        timeout=600.0,
    )

    raw_pages = response_dict.get("pages", [])

    # Deterministic auto-fill BEFORE placeholder — fills trivially
    # extractable slots without relying on LLM.
    raw_pages = _auto_fill_deterministic_slots(
        raw_pages,
        source_path="",
        source_text="",
        source_slug_map=source_slug_map,
    )

    # 2. If after retry+auto-fill some required slots are still missing,
    #    fill them with a clearly marked placeholder so every rendered
    #    page is structurally complete.
    filled_pages, missing_summary = _ensure_required_slots_filled(
        raw_pages,
        required_slots_by_type=required_slots_by_type,
    )
    if missing_summary:
        _logger.warning(
            "[generator] required slots still missing after retry+auto-fill, "
            "filled with placeholder: %s",
            missing_summary,
        )

    # 3. Build WikiPage objects. Use the resolved templates to render
    #    body markdown from slots via the section-aware renderer.
    type_from_analyzer: dict[str, str] = {
        p.slug: p.type.value if hasattr(p.type, "value") else str(p.type)
        for p in analysis.suggested_pages
    }
    # Carry analyzer-suggested tags as a fallback so generated pages keep
    # their classification even when the generator omits `tags`. Keyed by
    # slugified slug (matches the slug the generator emits).
    analyzer_tags: dict[str, list[str]] = {
        (_slugify(p.slug) or p.slug): list(p.tags) for p in analysis.suggested_pages
    }

    # Build an inverse slug→title map so the generator can resolve
    # wikilinks for the "参考来源" (references) slot — the LLM often
    # emits plain-text titles instead of [[slug]], especially for
    # source pages whose slugs the LLM can't predict. We inject the
    # map into the prompt below and also use it to post-process
    # rendered bodies.
    _source_title_to_slug: dict[str, str] = {}
    if source_slug_map:
        for raw_path, sl in source_slug_map.items():
            _stem = Path(raw_path).stem if raw_path else ""
            if _stem:
                _source_title_to_slug[_stem] = sl

    now = int(time.time() * 1000)
    pages: list[WikiPage] = []
    for p in filled_pages:
        title = p.get("title", "")
        slug = _slugify(title) or p.get("id", "")
        raw_type = (
            type_from_analyzer.get(slug)
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
            body_md = ""
        else:
            body_md = render_body(
                template_body=template.body_markdown,
                slots=p.get("slots", {}) or {},
                page_type=page_type,
                template_version=template.version or "",
            )

        # Fix: the LLM may emit guessed/pinyin wikilinks to source pages
        # (e.g. [[必备资料-11-月...]]) that don't match the deterministic
        # slug on disk. Scan rendered bodies and replace any [[wikilink]]
        # whose slugified form matches a known source-page slug.
        if source_slug_map and body_md:
            _known_source_slugs: set[str] = set(source_slug_map.values())
            def _replace_broken_source_wikilink(m: object) -> str:
                target = m.group(1).split("|")[0].split("#")[0].strip()
                canon = _slugify(target) or target
                for real_slug in _known_source_slugs:
                    if (_slugify(real_slug) or real_slug) == canon:
                        alias = m.group(1)[len(target):]  # |alias or #fragment
                        return f"[[{real_slug}{alias}]]"
                return m.group(0)
            body_md = re.sub(r"\[\[(.*?)\]\]", _replace_broken_source_wikilink, body_md)

        # Dedup relations: the LLM may emit multiple relation entries
        # for the same target (same slug, or different renderings of
        # the same concept that slugify to the same canonical form).
        # Keep only the highest-weight entry per slugified target.
        raw_relations = p.get("relations", []) or []
        deduped_relations: list[dict] = []
        seen_targets: set = set()
        for rel in sorted(raw_relations, key=lambda r: r.get("weight", 1.0), reverse=True):
            tgt = rel.get("target", "")
            if not tgt:
                continue
            canon = _slugify(tgt) or tgt
            if canon not in seen_targets:
                seen_targets.add(canon)
                deduped_relations.append(rel)

        pages.append(WikiPage(
            id=slug,
            title=p["title"],
            type=page_type,
            sources=[normalize_source_path(analysis.source_path, paths.root)],
            created_at=now,
            updated_at=now,
            body=body_md,
            grade=p.get("grade", "B"),
            processing_depth=p.get("processing_depth") or _DEPTH_BY_TYPE.get(page_type, "concept"),
            is_immutable=p.get("is_immutable", False),
            relations=parse_relations_from_response(deduped_relations),
            tags=_resolve_page_tags(p, slug, analyzer_tags),
            category=p.get("category", ""),
            taxonomy_sub=p.get("taxonomy_sub", ""),
        ))
    return pages


def _resolve_page_tags(
    page: dict,
    slug: str,
    analyzer_tags: dict[str, list[str]],
) -> list[str]:
    """Resolve controlled-namespace tags for a generated page.

    Priority: generator-emitted ``tags`` -> analyzer-suggested tags for this
    slug -> empty. Every returned tag is validated against the 8 controlled
    prefixes (``tag_namespace.is_valid``); invalid tags are dropped so the
    result always passes ``validate_tags``.
    """
    raw = page.get("tags") or analyzer_tags.get(slug) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [t for t in raw if isinstance(t, str) and is_valid_tag(t)]


# ---------------------------------------------------------------------------
# Internal helpers for v2.3 slot enforcement.
# ---------------------------------------------------------------------------


async def _call_with_slot_retry(
    *,
    provider,
    base_prompt: str,
    response_format: dict,
    required_slots_by_type: dict[PageType, list[str]],
    timeout: float = 180.0,
) -> dict:
    """Call the LLM, retry once if any required slot is missing or the call times out.

    Returns the parsed response dict (with ``pages`` key).
    """
    import httpx

    MAX_GEN_ATTEMPTS = 3  # initial + 2 retries
    last_missing: dict[str, list[str]] = {}
    last_response: dict = {}
    _json_mode = True  # first attempt uses response_format

    for attempt in range(MAX_GEN_ATTEMPTS):
        extra = ""
        if attempt > 0:
            if last_missing:
                lines = [
                    "## RETRY — YOUR LAST RESPONSE HAD EMPTY REQUIRED SLOTS",
                    "",
                    "These slots WERE missing or empty in your last response:",
                ]
                for ptype_name, names in last_missing.items():
                    lines.append(f"- {ptype_name}: {', '.join(names)}")
                lines.append("")
                lines.append("YOU MUST FILL EVERY ONE. Use these fallbacks if stuck:")
                lines.append("  references       → - [[<source-page-slug>]]")
                lines.append("  source_meta      → Extract URL/platform/date from source header")
                lines.append("  related_concepts → 2+ [[wikilinks]] to pages YOU defined in this response")
                lines.append("  related          → - [[<source-page-slug>]]")
                lines.append("  key_points       → 3+ facts from the source text")
                lines.append("  extracted_concepts → [[wikilinks]] to concepts/entities below")
                lines.append("  examples         → If none: \"来源未提供具体例子\"")
                lines.append("  ALL OTHERS       → \"来源未详述此方面\"")
                lines.append("")
                lines.append(
                    "EMPTY = RETRY AGAIN. PLACEHOLDER TEXT (..., 待补充, TBD) = RETRY AGAIN. "
                    "There is NO third chance — fill every slot this time."
                )
                extra = "\n\n" + "\n".join(lines) + "\n"
            else:
                # JSON parse failed — the model returned something that isn't
                # valid JSON despite the format instructions in the base
                # prompt. Drop ``response_format`` and re-emphasise.
                _json_mode = False
                extra = (
                    "\n\n## RETRY — JSON PARSE FAILED\n"
                    "Your previous response was NOT valid JSON. Re-read the "
                    "\"CRITICAL — JSON Format\" rules at the top. Output ONLY "
                    "the raw JSON object now:\n"
                )

        try:
            response = await provider.complete(
                messages=[{"role": "user", "content": base_prompt + extra}],
                response_format=response_format if _json_mode else None,
                timeout=timeout,
            )
        except (httpx.ReadTimeout, httpx.ConnectError) as exc:
            _logger.warning(
                "[Generator] LLM call timed out on attempt %d/%d: %s",
                attempt + 1, MAX_GEN_ATTEMPTS, exc,
            )
            if attempt == MAX_GEN_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Generator LLM timed out after {MAX_GEN_ATTEMPTS} attempts: {exc}"
                ) from exc
            continue

        try:
            response_dict = _parse_llm_response(response)
        except (ValueError, Exception) as exc:
            _logger.warning(
                "[Generator] LLM JSON parse failed on attempt %d/%d: %s",
                attempt + 1, MAX_GEN_ATTEMPTS, exc,
            )
            if attempt == MAX_GEN_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Generator LLM JSON parse failed after {MAX_GEN_ATTEMPTS} attempts: {exc}"
                ) from exc
            continue
        if not isinstance(response_dict, dict):
            _logger.warning(
                "[Generator] LLM returned non-dict on attempt %d/%d: %s",
                attempt + 1, MAX_GEN_ATTEMPTS, type(response_dict).__name__,
            )
            if attempt == MAX_GEN_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Generator LLM returned {type(response_dict).__name__}, expected dict "
                    f"(first 200 chars: {str(response)[:200]!r})"
                )
            continue
        last_response = response_dict

        # Detect empty extraction — LLM returned zero pages.
        # Trigger a retry with a stronger directive so the pipeline never
        # silently produces a source page with "(无摘要)".
        if not response_dict.get("pages"):
            _logger.warning(
                "[Generator] LLM returned empty pages list on attempt %d/%d",
                attempt + 1, MAX_GEN_ATTEMPTS,
            )
            if attempt == MAX_GEN_ATTEMPTS - 1:
                _logger.error(
                    "Generator LLM returned empty pages after %d attempts",
                    MAX_GEN_ATTEMPTS,
                )
                return {"pages": []}
            extra = (
                "\n\n## RETRY — EMPTY PAGES DETECTED\n"
                "Your previous response had NO pages at all (empty pages list). "
                "This is a pipeline error. You MUST extract at least:\n"
                "- 1 source page (type=source) with summary and metadata\n"
                "- 2+ entity or concept pages from the source content\n"
                "Even if the text seems short or unrelated, find SOMETHING "
                "to extract — names, terms, techniques, concepts, anything "
                "mentioned in the text. An empty extraction is worse than "
                "thin pages.\n"
            )
            _json_mode = False  # drop response_format on retry
            continue

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


def _auto_fill_deterministic_slots(
    pages: list[dict],
    *,
    source_path: str,
    source_text: str,
    source_slug_map: Optional[dict] = None,
) -> list[dict]:
    """Deterministic slot fills — no LLM needed, always correct.

    Runs BEFORE ``_ensure_required_slots_filled`` to reduce the number
    of placeholder-stuffed pages. Covers the slots that are trivially
    fillable from data already in scope:

    - ``references`` (concept): auto-fill ``[[<source-page-slug>]]``
    - ``source_meta`` (source): parse URL, platform, date from text header
    - ``related_concepts`` (concept): collect other concept/entity slugs
      defined in the same batch
    - ``related`` (entity): auto-fill ``[[<source-page-slug>]]``
    - ``extracted_concepts`` (source): collect concept/entity slugs
      from the same batch
    """
    import re as _re
    from pathlib import Path as _Path

    # Resolve the source-page slug for wikilinks
    source_slug: Optional[str] = None
    if source_slug_map:
        source_slug = source_slug_map.get(source_path)

    # Collect all concept/entity slugs from the same batch
    batch_slugs: list[str] = []
    for p in pages:
        ptype = p.get("type", "")
        title = p.get("title", "")
        slug = _slugify(title) or p.get("id", "")
        if slug and ptype in ("concept", "entity"):
            batch_slugs.append(slug)

    # --- Parse source_meta from source text header ---
    source_meta_text = ""
    # Try to extract URL
    url_match = _re.search(r'https?://[^\s\n"]+', source_text[:500])
    url_str = url_match.group(0).rstrip(".") if url_match else ""
    # Try to extract download date
    date_match = _re.search(
        r'下载时间[：:]\\s*(\\d{4}[-/]\\d{2}[-/]\\d{2})',
        source_text[:500],
    )
    date_str = date_match.group(1) if date_match else ""
    # Try to extract platform
    platform_match = _re.search(
        r'^(飞书云文档|微信公众号|QQ群|来源[：:].*)$',
        source_text[:500], _re.MULTILINE,
    )
    platform_str = platform_match.group(1).strip() if platform_match else ""
    # Source filename
    fname = _Path(source_path).stem if source_path else ""

    if url_str or platform_str or date_str or fname:
        parts = []
        if fname:
            parts.append(f"源文件: {fname}")
        if url_str:
            parts.append(f"来源: {url_str}")
        if platform_str and not platform_str.startswith("来源"):
            parts.append(f"平台: {platform_str}")
        if date_str:
            parts.append(f"下载时间: {date_str}")
        source_meta_text = "\\n".join(parts)

    # --- Walk pages and fill deterministic slots ---
    for p in pages:
        try:
            ptype = PageType(p.get("type"))
        except (ValueError, TypeError):
            continue
        slots = p.setdefault("slots", {})

        if ptype == PageType.CONCEPT:
            # references: always fillable from source page
            if _slot_is_empty(slots.get("references")) and source_slug:
                slots["references"] = f"- [[{source_slug}]]"
            # related_concepts: fill from batch peers
            if _slot_is_empty(slots.get("related_concepts")) and batch_slugs:
                my_title = p.get("title", "")
                my_slug = _slugify(my_title) or p.get("id", "")
                peers = [s for s in batch_slugs if s != my_slug][:5]
                if peers:
                    slots["related_concepts"] = "\n".join(f"- [[{s}]]" for s in peers)

        elif ptype == PageType.ENTITY:
            # related: always fillable from source page
            if _slot_is_empty(slots.get("related")) and source_slug:
                slots["related"] = f"- [[{source_slug}]]"

        elif ptype == PageType.SOURCE:
            # source_meta: parse from source header
            if _slot_is_empty(slots.get("source_meta")) and source_meta_text:
                slots["source_meta"] = source_meta_text
            # key_points: try to extract from source text if empty
            if _slot_is_empty(slots.get("key_points")):
                # Extract heading-prefixed lines as fallback key points
                heading_lines = _re.findall(
                    r'^#+\\s+(.+)', source_text[:3000], _re.MULTILINE,
                )
                # Or numbered list items
                numbered_items = _re.findall(
                    r'^\\d+[、.．]\\s*(.{10,120})$', source_text[:5000], _re.MULTILINE,
                )
                candidates = heading_lines[:5] or numbered_items[:5]
                if candidates:
                    slots["key_points"] = "\n".join(f"- {c}" for c in candidates)

    return pages


def _slot_is_empty(value) -> bool:
    """Check if a slot value is effectively empty."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0 or all(
            isinstance(v, str) and not v.strip() for v in value
        )
    return False


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