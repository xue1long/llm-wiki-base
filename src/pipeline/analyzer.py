"""Step 1: LLM extracts AnalysisResult from source text."""
import json
import logging
import re

from ..lib.budgeted import BudgetedLLM
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
每个建议页可带 0-N 个 tags (分类检索用). 每个 tag 必须是 `前缀/名称` 形式, 前缀
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
      "tags": ["genre/现言", "func/教程"]      // optional; default []
      // 受控命名空间: 前缀只能是 genre/ func/ char/ event/ mood/ entity/ scene_phase/ status/ 之一,
      // 形式为 "前缀/名称" (名称用中文/英文, 不要含空格). 不要使用其它前缀或裸标签(无 /).
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
    import logging as _logging
    _al = _logging.getLogger(__name__)

    prompt = ANALYZER_PROMPT.format(
        source_path=source_path,
        folder_context=folder_context or "(none)",
        existing_wiki_index=existing_wiki_index or "(empty)",
        source_text=source_text,
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
            llm_resp = await bl.call(
                prompt=prompt + extra,
                response_format=ANALYZER_RESPONSE_FORMAT if _json_mode else None,
            )

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


def _parse_llm_response(llm_resp) -> dict:
    """Parse ``LLMResponse.content`` (or a raw dict/str from mocks/tests) as JSON.

    Delegates to ``_pipeline_common.parse_llm_json`` — kept as a thin
    wrapper so existing test imports continue to work and the analyzer
    can be located quickly by callers searching for ``_parse_llm_response``.
    """
    return parse_llm_json(llm_resp)