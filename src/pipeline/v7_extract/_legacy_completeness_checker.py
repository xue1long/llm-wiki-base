"""Stage 3 of the V7 extract pipeline: detect incomplete source documents."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any

from .doc_classifier import DocType


_MIN_LENGTH_BY_TYPE = {
    DocType.SINGLE_METHOD: 400,
    DocType.MULTI_SECTION: 200,
    DocType.COLLECTION: 800,
    DocType.QA_CHAT: 800,
    DocType.LIST: 400,
    DocType.TOOL: 200,
}
_PROMISED_COUNT_RE = re.compile(
    r"^\s*#.*?(\d+)\s*(?:条|篇|项|个|种|章|节|招)",
    re.MULTILINE,
)
_NUMBERED_ITEM_RE = re.compile(r"^\s*\d+\s*[.、,，)]\s*\S", re.MULTILINE)
_NAMED_SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十百]+、", re.MULTILINE)
_INTRO_MARKERS = (
    "正文内容缺失",
    "仅有引言",
    "内容不完整",
    "正文缺失",
    "内容缺失",
)


def check_completeness(
    content: str,
    doc_type: DocType,
    *,
    llm=None,
) -> tuple[bool, str]:
    """Return ``(is_complete, reason)`` for one classified document.

    The deterministic checks run first.  If they reject an otherwise
    ambiguous document, an optional LLM may confirm or override that result;
    malformed or unavailable LLM responses fall back to the heuristic result.
    """
    text = (content or "").strip()
    heuristic = _check_heuristic(text, doc_type)
    if heuristic[0] or llm is None or doc_type is DocType.INCOMPLETE:
        return heuristic

    llm_result = _check_with_llm(text, doc_type, llm)
    return llm_result if llm_result is not None else heuristic


def _check_heuristic(text: str, doc_type: DocType) -> tuple[bool, str]:
    if doc_type is DocType.INCOMPLETE:
        return False, "doc_type=incomplete"
    if not text:
        return False, "empty_content"

    promised_count = _extract_promised_count(text)
    if promised_count is not None:
        actual_count = _count_actual_units(text)
        if actual_count < promised_count:
            return (
                False,
                f"promised_count={promised_count} > actual_count={actual_count}",
            )

    if _is_intro_only(text):
        return False, "intro_only"

    minimum = _MIN_LENGTH_BY_TYPE[doc_type]
    if len(text) < minimum:
        return False, f"below_length_threshold={minimum} (actual={len(text)})"

    return True, ""


def _extract_promised_count(text: str) -> int | None:
    match = _PROMISED_COUNT_RE.search(text)
    return int(match.group(1)) if match else None


def _count_actual_units(text: str) -> int:
    return max(
        len(_NUMBERED_ITEM_RE.findall(text)),
        len(_NAMED_SECTION_RE.findall(text)),
    )


def _is_intro_only(text: str) -> bool:
    if any(marker in text for marker in _INTRO_MARKERS):
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headings = [line for line in lines if line.startswith("#")]
    body_lines = [line for line in lines if not line.startswith("#")]
    return len(text) < 800 and len(headings) == 1 and len(body_lines) <= 2


def _check_with_llm(text: str, doc_type: DocType, llm: Any) -> tuple[bool, str] | None:
    complete = getattr(llm, "complete", None)
    if not callable(complete):
        return None

    try:
        response = complete(
            prompt_kind="completeness",
            user_prompt=(
                "Classify whether this source document is complete. "
                f"Document type: {doc_type.value}. Return JSON with "
                'boolean "complete" and string "reason".\n\n'
                f"{text}"
            ),
            system_prompt="Return only a JSON object.",
            max_tokens=256,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                response = asyncio.run(response)
            else:
                return None
    except Exception:
        return None

    return _parse_llm_result(response)


def _parse_llm_result(response: Any) -> tuple[bool, str] | None:
    if isinstance(response, dict):
        payload = response
    elif isinstance(response, str):
        raw = response.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
    else:
        return None

    value = payload.get("complete", payload.get("is_complete"))
    if not isinstance(value, bool):
        return None
    reason = payload.get("reason", payload.get("rationale", ""))
    return value, reason if isinstance(reason, str) else str(reason)
