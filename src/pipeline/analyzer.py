"""Step 1: LLM extracts AnalysisResult from source text."""
import json
import logging
import uuid

from ..knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from ..knowledge.core.object import KnowledgeType
from ..lib.budgeted import BudgetedLLM
from ..wiki.features.tag_namespace import build_tag_prompt_section
from ..wiki.core.types import PageType
from ._pipeline_common import parse_llm_json
from .schemas import AnalysisResult, ConceptMention, EntityMention, PageSpec


_logger = logging.getLogger(__name__)


ANALYZER_PROMPT = """You are analyzing a source document for a knowledge base.

## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no
   introductory text, no concluding remarks.
2. Your response MUST start with `{{` and end with `}}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

Do NOT output chain-of-thought, hidden reasoning, or a thinking
transcript. Reason internally and emit only the requested JSON.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段:
summary、key_facts、entities/concepts 的 name 和 context、
suggested_pages 的 title/reasoning/tags。Slugs 使用中文 (CJK) 或
ASCII kebab-case — 保留概念的自然字面，**禁止拼音转写**。专有名词/英文
术语在 ASCII 段仍保持原始写法 (e.g. OpenAI, GPT-5, Transformer)。

## Context
- Source: {source_path}
- Folder: {folder_context}
- Existing wiki index:
{existing_wiki_index}

## Source text
{source_text}

## Tags guidance (受控命名空间)
{tag_namespace_rules}

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
      "type": "{page_types}",
      "slug": "...",
      "title": "...",
      "reasoning": "...",
      "grade": "A|B|C",                    // optional; default B
      "processing_depth": "concept|memory", // optional; default concept
      "is_immutable": false,               // optional; default false
      "tags": ["题材/现言", "功能/教程"]      // optional; default []
      // 受控命名空间: 前缀只能是 题材/ 功能/ 角色/ 事件/ 情绪/ 实体/ 场景阶段/ 状态/ 素材/ 可信度/ 之一,
      // 形式为 "前缀/名称" (名称用中文/英文, 不要含空格). 不要使用其它前缀或裸标签(无 /).
    }}
  ],
  "links_to_existing": ["<slug>"]          // existing wiki pages this references
}}
"""


ANALYZER_JSON_PROMPT = """You are analyzing a source document to extract structured knowledge claims.

## CRITICAL — JSON Format
1. Output ONLY the raw JSON object — no markdown fences (```), no
   introductory text, no concluding remarks.
2. Your response MUST start with `{{` and end with `}}`.
3. Do NOT wrap the JSON in ```json ... ``` blocks.
4. All strings must be properly escaped (double quotes, not single quotes).

Do NOT output chain-of-thought, hidden reasoning, or a thinking
transcript. Reason internally and emit only the requested JSON.

## Language
默认使用中文 (Simplified Chinese) 撰写所有用户可见的字符串字段。
Slugs 使用中文 (CJK) 或 ASCII kebab-case — 保留概念的自然字面，**禁止拼音转写**。

## Context
- Source: {source_path}
- Folder: {folder_context}
- Existing wiki index:
{existing_wiki_index}

## Source text
{chunk_context}{source_text}

## Page numbers
The source text may contain `<!-- page: N -->` markers indicating page
boundaries in the original document. When these markers are present,
include the page number in each evidence entry's `page` field.

## Task
Extract structured knowledge claims as a JSON object matching this schema:
{{
  "source_id": "<source path>",
  "type": "{knowledge_types}",
  "title": "<candidate title>",
  "claims": [
    {{"statement": "<claim text>", "confidence": 0.0-1.0, "evidence_refs": [0, 1]}}  // 0-based: valid range 0 to len(evidence)-1, never use len(evidence)
  ],
  "evidence": [
    {{"source_path": "<path>", "page": null, "quote": "<supporting text excerpt>"}}
  ]
}}

Rules:
- source_id: the path of the source document being analyzed
- type: one of {knowledge_types}
- title: a concise title summarizing the main topic (3-15 words)
- claims: 3-10 factual claims extracted from the source. Each claim must have:
  - statement: the claim text (one sentence, self-contained)
  - confidence: how certain this claim is (0.0-1.0) based on source quality
  - evidence_refs: **0-based** integer indices (0 = first, N-1 = last). Never output N or higher.
- evidence: supporting excerpts from the source. Each entry:
  - source_path: path to source
  - page: page number or null
  - quote: exact text excerpt supporting one or more claims
"""


# ---------------------------------------------------------------------------
# AnalyzerOutputParser — 3-tier validation for JSON analyser output
# ---------------------------------------------------------------------------

class AnalyzerOutputParser:
    """Parse and validate raw LLM JSON output into a KnowledgeCandidate.

    3-tier validation (applied in order):

    1. **Syntax check** — Is the input a non-empty dict?
       If not (``None`` / ``{}`` / non-dict) → REJECTED with confidence 0.0.

    2. **Schema check** — Required fields present?
       - ``source_id`` missing → REJECTED (no source = untraceable)
       - ``type`` missing → default ``KnowledgeType.CONCEPT``, confidence *= 0.3
       - ``title`` missing → truncated from ``claims[0].statement`` (first 80
         chars), confidence *= 0.3

    3. **Content check** — ``claims`` list non-empty?
       Empty → confidence = 0.3, status remains PENDING (flagged for human
       review — the candidate may still be salvageable).

    The parser is additive: each missing field decays confidence
    multiplicatively (1.0 → 0.3 → 0.09 …), and the content check assigns
    a floor of 0.3.  A REJECTED status (missing ``source_id`` or syntax
    failure) is terminal — confidence is zeroed and the candidate should
    not proceed to promotion.
    """

    def parse(
        self,
        raw: dict | None,
        source_path: str = "",
        chunk_index: int | None = None,
        chunk_total: int | None = None,
    ) -> KnowledgeCandidate:
        """Validate *raw* dict and return a KnowledgeCandidate.

        Parameters
        ----------
        raw:
            Parsed JSON dict from the LLM response. May be ``None`` or
            empty when JSON parsing failed upstream.
        source_path:
            Fallback source identifier used when *raw* omits
            ``source_id`` (set as the candidate's ``source_id`` but
            status is still REJECTED).
        """
        # -- Tier 1: Syntax check -------------------------------------------------
        if not isinstance(raw, dict) or not raw:
            return KnowledgeCandidate(
                id=_generate_candidate_id(),
                source_id=source_path or "unknown",
                type=KnowledgeType.CONCEPT,
                title="Parse Error",
                claims=[],
                confidence=0.0,
                evidence=[],
                raw_llm_output=raw if isinstance(raw, dict) else {},
                status=CandidateStatus.REJECTED,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
            )

        confidence = 1.0
        status = CandidateStatus.PENDING

        # -- Tier 2: Schema check -------------------------------------------------
        source_id = raw.get("source_id", "")
        if not source_id:
            status = CandidateStatus.REJECTED

        # default page type is "concept"; decay confidence when inferred
        if "type" not in raw:
            confidence *= 0.3
            ktype = KnowledgeType.CONCEPT
        else:
            try:
                ktype = KnowledgeType(raw["type"])
            except ValueError:
                confidence *= 0.3
                ktype = KnowledgeType.CONCEPT

        # title: truncate from first claim when missing
        if "title" not in raw or not raw.get("title"):
            claims = raw.get("claims", [])
            if claims and isinstance(claims[0], dict) and claims[0].get("statement"):
                # title missing → derive from first claim, max 80 chars
                derived = str(claims[0]["statement"])[:80]
            else:
                derived = ""
            confidence *= 0.3
            title = derived
        else:
            title = raw.get("title", "")

        # -- Tier 3: Content check -------------------------------------------------
        claims = raw.get("claims", [])
        if not isinstance(claims, list):
            claims = []
        if not claims:
            confidence = 0.3

        evidence = raw.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []

        return KnowledgeCandidate(
            id=_generate_candidate_id(),
            source_id=source_id,
            type=ktype,
            title=title,
            claims=claims,
            confidence=confidence,
            evidence=evidence,
            raw_llm_output=raw,
            status=status,
            chunk_index=chunk_index,
            chunk_total=chunk_total,
        )


def _generate_candidate_id() -> str:
    """Generate a unique candidate id."""
    return f"cand_{uuid.uuid4().hex[:12]}"


async def analyze(
    source_text: str,
    source_ext: str,
    existing_wiki_index: str,
    folder_context: str,
    provider,
    task_id: str = "test",
    source_path: str = "raw/sources/test",
    output_format: str = "markdown",
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> AnalysisResult | KnowledgeCandidate:
    """Step 1: LLM call -> AnalysisResult or KnowledgeCandidate.

    When *output_format* is ``"json"``, the LLM is instructed to produce
    KnowledgeCandidate-shaped JSON and the result is passed through
    :class:`AnalyzerOutputParser` for 3-tier validation.
    When *output_format* is ``"markdown"`` (default), the existing
    AnalysisResult path is preserved exactly.
    """
    import logging as _logging
    _al = _logging.getLogger(__name__)

    if output_format != "json":
        import warnings as _warnings
        _warnings.warn(
            "markdown output_format is deprecated. Use output_format='json'.",
            DeprecationWarning,
            stacklevel=2,
        )

    if output_format == "json":
        return await _analyze_json(
            source_text=source_text,
            existing_wiki_index=existing_wiki_index,
            folder_context=folder_context,
            provider=provider,
            source_path=source_path,
            _al=_al,
            chunk_index=chunk_index,
            chunk_total=chunk_total,
        )

    prompt = ANALYZER_PROMPT.format(
        source_path=source_path,
        folder_context=folder_context or "(none)",
        existing_wiki_index=existing_wiki_index or "(empty)",
        source_text=source_text,
        tag_namespace_rules=build_tag_prompt_section(),
        # Page-layer only: claim/decision/procedure/event are knowledge-layer
        # and fold to concept downstream (see wiki-spec-sync plan §0.2).
        page_types="|".join(
            t.value for t in PageType
            if t in (PageType.SOURCE, PageType.ENTITY, PageType.CONCEPT, PageType.SYNTHESIS)
        ),
    )

    ANALYZER_RESPONSE_FORMAT = {
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
    }

    MAX_ATTEMPTS = 2
    _json_mode = True
    last_error: str | None = None

    # If startup check already marked this provider incompatible, skip the
    # response_format probe entirely on the first attempt.
    if getattr(provider, "_response_format_ok", None) is False:
        _json_mode = False

    for attempt in range(MAX_ATTEMPTS):
        extra = ""
        if attempt > 0:
            _json_mode = False
            extra = (
                "\n\n## RETRY — JSON PARSE FAILED\n"
                "Your previous response was NOT valid JSON. Re-read the "
                "\"CRITICAL — JSON Format\" rules at the top. "
                "Failure reason: " + (last_error or "unknown") + "\n"
                "Reply with the raw JSON object now:\n"
            )

        async with BudgetedLLM(model="gpt-4o-mini", op="analyzer", provider=provider) as bl:
            try:
                llm_resp = await bl.call(
                    prompt=prompt + extra,
                    response_format=ANALYZER_RESPONSE_FORMAT if _json_mode else None,
                )
            except RuntimeError as exc:
                exc_str = str(exc)
                if "response_format" in exc_str.lower() and "400" in exc_str:
                    _al.warning(
                        "[analyzer] response_format rejected on attempt %d/%d: %s",
                        attempt + 1, MAX_ATTEMPTS, exc,
                    )
                    if attempt == MAX_ATTEMPTS - 1:
                        raise
                    _json_mode = False
                    extra = (
                        "\n\n## RETRY — RESPONSE FORMAT REJECTED\n"
                        "The provider rejected the structured output format. "
                        "Reply with the raw JSON object now:\n"
                    )
                    continue
                raise

        try:
            response = _parse_llm_response(llm_resp)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            _al.warning(
                "[analyzer] JSON parse failed on attempt %d/%d: %s",
                attempt + 1, MAX_ATTEMPTS, exc,
            )
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Analyzer LLM response was not valid JSON ({len(str(llm_resp))} chars): {exc}"
                ) from exc
            continue

        if not isinstance(response, dict):
            last_error = f"Returned {type(response).__name__}, expected dict"
            _al.warning(
                "[analyzer] non-dict response on attempt %d/%d: %s",
                attempt + 1, MAX_ATTEMPTS, last_error,
            )
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Analyzer LLM response was a {type(response).__name__}, expected dict "
                    f"(first 200 chars: {str(llm_resp)[:200]!r})"
                )
            continue

        break

    return AnalysisResult(
        task_id=task_id,
        source_path=source_path,
        summary=response.get("summary", ""),
        key_facts=response.get("key_facts", []),
        entities=[
            EntityMention(
                name=e.get("name", ""),
                slug=e.get("slug", ""),
                # Default to "concept" when LLM omits 'type' — observed in
                # production (api.minimax.chat occasionally drops it), and
                # not worth crashing the whole ingest.
                type=e.get("type", "concept"),
                context=e.get("context", ""),
                confidence=e.get("confidence", 0.0),
            )
            for e in response.get("entities", [])
        ],
        concepts=[
            ConceptMention(**{k: v for k, v in c.items()
                              if k in ("name", "slug", "context", "confidence", "concept")})
            for c in response.get("concepts", [])
        ],
        suggested_pages=[
            PageSpec(**{k: v for k, v in p.items()
                        if k in ("type", "slug", "title", "reasoning",
                                 "grade", "processing_depth", "is_immutable", "tags")})
            for p in response.get("suggested_pages", [])
        ],
        links_to_existing=response.get("links_to_existing", []),
        folder_context=folder_context,
    )


# -- JSON response schema (module-level so _analyze_json can reference it) --
_ANALYZER_JSON_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "type": {"type": "string"},
        "title": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_refs": {"type": "array", "items": {"type": "integer"}},
                },
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "page": {"type": ["integer", "null"]},
                    "quote": {"type": "string"},
                },
            },
        },
    },
    "required": ["source_id", "type", "title", "claims"],
}


async def _analyze_json(
    source_text: str,
    existing_wiki_index: str,
    folder_context: str,
    provider,
    source_path: str,
    _al: logging.Logger,
    chunk_index: int | None = None,
    chunk_total: int | None = None,
) -> KnowledgeCandidate:
    """JSON mode: LLM call -> KnowledgeCandidate with 3-tier validation.

    Retry once if JSON parse fails (different temperature via removing
    ``response_format``).  If both attempts fail, return a REJECTED
    candidate instead of raising.
    """
    _chunk_ctx = ""
    if chunk_index is not None and chunk_total is not None:
        _chunk_ctx = (
            f"\n## Chunk context\n"
            f"This is chunk {chunk_index + 1}/{chunk_total} of a large document. "
            f"Extract claims that are MOST specific to this chunk's content. "
            f"Cross-chunk entity references will be merged later — you do NOT "
            f"need to reference other chunks.\n\n"
        )
    prompt = ANALYZER_JSON_PROMPT.format(
        source_path=source_path,
        folder_context=folder_context or "(none)",
        existing_wiki_index=existing_wiki_index or "(empty)",
        source_text=source_text,
        chunk_context=_chunk_ctx,
        knowledge_types="|".join(t.value for t in KnowledgeType),
    )

    MAX_ATTEMPTS = 2
    _json_mode = True
    last_error: str | None = None
    response: dict | None = None

    # If startup check already marked this provider incompatible, skip the
    # response_format probe entirely on the first attempt.
    if getattr(provider, "_response_format_ok", None) is False:
        _json_mode = False

    for attempt in range(MAX_ATTEMPTS):
        extra = ""
        if attempt > 0:
            _json_mode = False
            extra = (
                "\n\n## RETRY — JSON PARSE FAILED\n"
                "Your previous response was NOT valid JSON. Re-read the "
                "\"CRITICAL — JSON Format\" rules at the top. "
                "Failure reason: " + (last_error or "unknown") + "\n"
                "Reply with the raw JSON object now:\n"
            )

        async with BudgetedLLM(model="gpt-4o-mini", op="analyzer-json", provider=provider) as bl:
            try:
                llm_resp = await bl.call(
                    prompt=prompt + extra,
                    response_format=_ANALYZER_JSON_RESPONSE_FORMAT if _json_mode else None,
                )
            except RuntimeError as exc:
                exc_str = str(exc)
                if "response_format" in exc_str.lower() and "400" in exc_str:
                    _al.warning(
                        "[analyzer-json] response_format rejected on attempt %d/%d: %s",
                        attempt + 1, MAX_ATTEMPTS, exc,
                    )
                    if attempt == MAX_ATTEMPTS - 1:
                        raise
                    _json_mode = False
                    extra = (
                        "\n\n## RETRY — RESPONSE FORMAT REJECTED\n"
                        "The provider rejected the structured output format. "
                        "Reply with the raw JSON object now:\n"
                    )
                    continue
                raise

        try:
            response = _parse_llm_response(llm_resp)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            _al.warning(
                "[analyzer-json] JSON parse failed on attempt %d/%d: %s",
                attempt + 1, MAX_ATTEMPTS, exc,
            )
            if attempt == MAX_ATTEMPTS - 1:
                # Both attempts exhausted — return REJECTED candidate
                parser = AnalyzerOutputParser()
                return parser.parse({}, source_path=source_path, chunk_index=chunk_index, chunk_total=chunk_total)
            continue

        if not isinstance(response, dict):
            last_error = f"Returned {type(response).__name__}, expected dict"
            _al.warning(
                "[analyzer-json] non-dict response on attempt %d/%d: %s",
                attempt + 1, MAX_ATTEMPTS, last_error,
            )
            if attempt == MAX_ATTEMPTS - 1:
                parser = AnalyzerOutputParser()
                return parser.parse({}, source_path=source_path, chunk_index=chunk_index, chunk_total=chunk_total)
            continue

        break

    # JSON parse succeeded — run 3-tier validation
    parser = AnalyzerOutputParser()
    return parser.parse(response, source_path=source_path, chunk_index=chunk_index, chunk_total=chunk_total)


def _parse_llm_response(llm_resp) -> dict:
    """Parse ``LLMResponse.content`` (or a raw dict/str from mocks/tests) as JSON.

    Delegates to ``_pipeline_common.parse_llm_json`` — kept as a thin
    wrapper so existing test imports continue to work and the analyzer
    can be located quickly by callers searching for ``_parse_llm_response``.
    """
    return parse_llm_json(llm_resp)
