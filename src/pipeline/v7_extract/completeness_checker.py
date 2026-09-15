"""Stage 3 of the V7 extract pipeline: detect incomplete source documents.

v3 (plan 2026-09-15): pure-LLM check with P5 decoupling.

P5 says Stage 3 must judge the *body* independently, regardless of
what Stage 1 decided. v2 short-circuited ``if doc_type is
INCOMPLETE: return False`` — that meant a Stage-1 error would skip
Stage 3 entirely. v3 keeps the doc_type as a *soft hint* in the
prompt but the LLM re-evaluates from scratch.

Heuristic-only logic was deleted (T2.2). The check is now a single
async LLM call. P2 guarantees ``check_completeness`` never raises — a
return value of ``(False, "stage3_failed: ...")`` indicates failure.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve

if TYPE_CHECKING:
    from .prompts.ast import PromptTemplate


log = logging.getLogger(__name__)


# v3: this module no longer defines heuristics or DocType references.
# The doc_type argument is now a *soft hint* (str) — callers pass
# whatever Stage 1 returned, but Stage 3 does not depend on it.


async def check_completeness(
    content: str,
    doc_type_hint: str = "unknown",
    *,
    llm: LLMClient,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """Decide whether ``content`` is substantial enough to extract from.

    Args:
        content: full document body (Stage 1 has already trimmed).
        doc_type_hint: what Stage 1 thought the doc_type was. Treated as
            a *soft hint* in the prompt — Stage 3 does its own
            judgement (P5).
        llm: any ``LLMClient`` implementation.
        project_root: passed through to ``prompts_resolver.resolve``.

    Returns:
        ``(is_complete, reason)``. Always returns — never raises
        (P2). On every failure mode the result is
        ``(False, "stage3_failed: <reason>")``.
    """
    template = _resolve_completeness_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "text": content,
        "doc_type_hint": doc_type_hint,
        "content_limit": "8000",
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="completeness",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=256,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            return _payload_to_result(payload)
        except LLMResponseError as e:
            last_error = e
            log.info(
                "check_completeness: response failed validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "check_completeness: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue

    log.error(
        "check_completeness: all %d retries exhausted, returning False. last_error=%r",
        max_retries, last_error,
    )
    return False, f"stage3_failed_after_{max_retries}_retries: {last_error}"


def _payload_to_result(payload: dict) -> tuple[bool, str]:
    complete = payload["complete"]
    reason = payload.get("reason") or ""
    return bool(complete), str(reason)


def _resolve_completeness_template(
    project_root: Path | str | None,
) -> "PromptTemplate":
    """Resolve the completeness prompt; raise RuntimeError on config error."""
    try:
        return resolve("completeness", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 completeness prompt is not available: {e}. "
            f"Check that prompts/builtin/completeness.toml is installed."
        ) from e
