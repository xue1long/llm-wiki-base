"""Stage 3 of the V7 extract pipeline: detect incomplete source documents.

v3 (plan 2026-09-15): pure-LLM check with P5 decoupling.

P5 says Stage 3 must judge the *body* independently, regardless of
what Stage 1 decided. v2 short-circuited ``if doc_type is
INCOMPLETE: return False`` — that meant a Stage-1 error would skip
Stage 3 entirely. v3 keeps the doc_type as a *soft hint* in the
prompt but the LLM re-evaluates from scratch.

Heuristic-only logic was deleted (T2.2). The check is now a single
async LLM call.

Task 6 (plan 2026-09-17 Stage 3 remediation): returns
``CompletenessResult | None``. Technical failure (LLM timeout /
parse error / schema invalid) returns ``None`` per Failure Contract
(2026-09-17-remediation-contract-freeze §1) — technical failure
MUST NOT be disguised as INCOMPLETE.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
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


class CompletenessStatus(str, Enum):
    """Stage 3 outcome (master plan §3.5 / Task 6).

    Maps to ExtractionStatus five-state in the caller via stage-local
    enum → ExtractionStatus mapping (not direct assignment).

    Failure is signalled two ways:
      - ``None`` return from :func:`check_completeness` (preferred)
      - ``TECHNICAL_FAILURE`` enum value (defense in depth)
    """

    COMPLETE = "complete"                  # body is substantial; proceed
    INCOMPLETE = "incomplete"              # provably incomplete body
    UNCERTAIN = "uncertain"                # LLM ran but cannot judge semantically
    TECHNICAL_FAILURE = "technical_failure"  # LLM/parse/timeout; never routed as INCOMPLETE


@dataclass
class CompletenessResult:
    """Stage 3 output contract (Task 6 / Failure Contract §1)."""

    status: CompletenessStatus
    reason_codes: list[str]
    evidence_refs: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    checker_fingerprint: str = ""  # Contract §4.4 — every stage exposes *_fingerprint
    warnings: list[str] = field(default_factory=list)
    technical_error: str | None = None  # only set when status == TECHNICAL_FAILURE


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
    structural_summary: dict | None = None,  # consumed by Task 7
) -> CompletenessResult | None:
    """Decide whether ``content`` is substantial enough to extract from.

    Args:
        content: full document body (Stage 1 has already trimmed).
        doc_type_hint: what Stage 1 thought the doc_type was. Treated as
            a *soft hint* in the prompt — Stage 3 does its own
            judgement (P5).
        llm: any ``LLMClient`` implementation.
        project_root: passed through to ``prompts_resolver.resolve``.
        structural_summary: optional Stage 2 structural signals
            (Task 7 will use this; accepted here so Task 6 callers can
            pass it through without churn).

    Returns:
        ``CompletenessResult`` on every successful LLM judgement.
        ``None`` iff all retries exhausted — per Failure Contract
        (§1): technical failure is signalled by ``None``, not by a
        fake ``INCOMPLETE`` status that would silently route the
        source to the skip-cache.
    """
    template = _resolve_completeness_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "text": content,
        "doc_type_hint": doc_type_hint,
        "content_limit": "8000",
    })
    # Task 7 will thread structural_summary through the prompt. Task 6
    # accepts it but does not yet consume it — keep the param to
    # avoid forcing Task 7 callers to update signatures twice.
    del structural_summary

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
        "check_completeness: all %d retries exhausted, returning None. last_error=%r",
        max_retries, last_error,
    )
    # Per Failure Contract: technical failure -> None.
    # NOT a CompletenessResult(status=INCOMPLETE) — that would smuggle
    # a technical failure into the skip-cache path.
    return None


def _payload_to_result(payload: dict) -> CompletenessResult:
    """Translate the LLM JSON payload into a structured result.

    Distinguishes UNCERTAIN (semantic ambiguity, review) from
    INCOMPLETE (provably incomplete, skip-cache). The LLM signals
    UNCERTAIN via an ``assessment: "uncertain"`` field or a
    non-boolean ``complete`` value (treated as ambiguous rather than
    silently coerced to True/False).
    """
    assessment = payload.get("assessment")
    raw_complete = payload.get("complete")
    reason = payload.get("reason") or ""

    if assessment == "uncertain" or not isinstance(raw_complete, bool):
        status = CompletenessStatus.UNCERTAIN
    elif raw_complete:
        status = CompletenessStatus.COMPLETE
    else:
        status = CompletenessStatus.INCOMPLETE

    confidence = payload.get("confidence")
    evidence_refs = payload.get("evidence_refs") or []

    return CompletenessResult(
        status=status,
        reason_codes=[reason] if reason else [],
        evidence_refs=list(evidence_refs),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        checker_fingerprint="checker-v6",
    )


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