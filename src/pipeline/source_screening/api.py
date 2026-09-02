from __future__ import annotations

from typing import Any

from src.lib.budgeted import BudgetedLLM
from src.pipeline._pipeline_common import parse_llm_json

from .rules import classify_by_rules, is_obvious_boilerplate
from .types import ScreeningResult


_CONTENT_TYPES = {"outline", "tutorial", "setting", "dialogue", "material", "unknown"}


def _llm_prompt(source_path: str, source_text: str) -> str:
    return f"""判断这份源文档是否与网文写作知识库相关。只输出 JSON，不要 markdown：
{{"relevant": true, "content_type": "outline|tutorial|setting|dialogue|material|unknown", "confidence": 0.0, "reason": "一句话原因"}}
source_path: {source_path}
source_text:
{source_text[:12000]}
"""


async def screen_source(source_path: str, source_text: str, *, prefilter_result, provider=None) -> ScreeningResult:
    if is_obvious_boilerplate(source_text) or (
        prefilter_result.action == "skip"
        and prefilter_result.reason.startswith("English-only")
    ):
        return ScreeningResult("skip", reason=prefilter_result.reason or "obvious boilerplate", method="rule")

    rule_result = classify_by_rules(source_path, source_text)
    if rule_result is not None:
        content_type, reason = rule_result
        return ScreeningResult("accept", content_type, 1.0, reason, "rule")

    if provider is None:
        return ScreeningResult("review", reason="insufficient deterministic signals", method="fallback")

    try:
        model = getattr(provider, "model", "gpt-4o-mini")
        async with BudgetedLLM(model=model, op="source-screening", provider=provider, max_output_tokens=512) as llm:
            raw = await llm.call(_llm_prompt(source_path, source_text))
        payload: dict[str, Any] = parse_llm_json(raw)
        confidence = float(payload.get("confidence", 0.0))
        relevant = payload.get("relevant")
        content_type = str(payload.get("content_type", "unknown"))
        if content_type not in _CONTENT_TYPES:
            content_type = "unknown"
        reason = str(payload.get("reason", "LLM screening"))
        if not 0.0 <= confidence <= 1.0 or confidence < 0.7:
            return ScreeningResult("review", content_type, max(0.0, min(confidence, 1.0)), reason, "llm")
        if relevant is True:
            return ScreeningResult("accept", content_type, confidence, reason, "llm")
        if relevant is False:
            return ScreeningResult("skip", content_type, confidence, reason, "llm")
        return ScreeningResult("review", content_type, confidence, reason, "llm")
    except Exception as exc:
        return ScreeningResult("review", reason=f"screening unavailable: {type(exc).__name__}", method="fallback")
