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

Task 7 (plan 2026-09-17 Stage 3 remediation): bounded evidence
pack — HEAD/TAIL + 3 mid samples + Stage 2 structural signals, hard
budget 5500 bytes per Bounded Evidence Contract §3.2. Stage 3
consumes Stage 2's ``SegmentationResult`` via the ``structural_summary``
parameter, so a 100KB source is never fed whole to the LLM.
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


# Task 7 / Bounded Evidence Contract §3.2 — Stage 3 hard budget.
# 2000 (HEAD) + 2000 (TAIL) + 3*500 (mid samples @ 25/50/75%) = 5500.
EVIDENCE_PACK_BUDGET_BYTES = 5500
_HEAD_TAIL_BYTES = 2000
_MID_SAMPLE_BYTES = 500
_MID_SAMPLE_POSITIONS = (0.25, 0.50, 0.75)


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


def _build_evidence_pack(
    content: str,
    structural_summary: dict | None,
    fingerprint: str,
) -> tuple[str, dict]:
    """Build the bounded evidence pack + meta summary (Task 7).

    Bounded Evidence Contract §3.2: HEAD (2000) + TAIL (2000) + 3 mid
    samples (500 each at 25/50/75%) + Stage 2 signals — total ≤ 5500
    bytes regardless of ``content`` length. The LLM is fed this pack
    instead of the raw full text, so 100KB sources do not overflow
    the context window.

    Returns ``(pack, meta)`` where ``meta`` is a JSON-serializable
    summary of what the pack contains (used in tests + future
    audit logging).
    """
    n = len(content)
    meta: dict = {
        "total_bytes": n,
        "has_head": True,
        "has_tail": n > _HEAD_TAIL_BYTES,
        "mid_samples": 0,
        "stage2_provided": bool(structural_summary),
        "checker_fingerprint": fingerprint,
    }

    head = content[:_HEAD_TAIL_BYTES]
    tail = content[-_HEAD_TAIL_BYTES:] if n > _HEAD_TAIL_BYTES else ""

    mid_samples: list[str] = []
    if n > _HEAD_TAIL_BYTES * 2:
        for pct in _MID_SAMPLE_POSITIONS:
            pos = int(n * pct)
            mid_samples.append(content[pos:pos + _MID_SAMPLE_BYTES])
    meta["mid_samples"] = len(mid_samples)

    if structural_summary:
        signal_text = "\n".join(f"{k}={v}" for k, v in structural_summary.items())
    else:
        signal_text = "stage2=not_provided"

    parts = [
        f"=== HEAD (first {_HEAD_TAIL_BYTES} chars) ===\n{head}",
        f"=== TAIL (last {_HEAD_TAIL_BYTES} chars) ===\n{tail}",
        f"=== STAGE 2 SIGNALS ===\n{signal_text}",
        f"=== MID SAMPLES (3 × {_MID_SAMPLE_BYTES} chars @ 25/50/75) ===",
    ]
    for i, sample in enumerate(mid_samples, start=1):
        parts.append(f"[mid-{i}]\n{sample}")
    pack = "\n".join(parts)

    # Hard budget cap (Bounded Evidence Contract §3.6 invariant).
    pack_bytes = pack.encode("utf-8")
    if len(pack_bytes) > EVIDENCE_PACK_BUDGET_BYTES:
        pack = pack_bytes[:EVIDENCE_PACK_BUDGET_BYTES].decode("utf-8", errors="ignore")
    meta["evidence_bytes"] = len(pack.encode("utf-8"))
    return pack, meta


async def check_completeness(
    content: str,
    doc_type_hint: str = "unknown",
    *,
    llm: LLMClient,
    project_root: Path | str | None = None,
    max_retries: int = 3,
    structural_summary: dict | None = None,
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
            (Task 7). Fed into the evidence pack so the LLM sees
            how Stage 2 partitioned the body without us sending
            the raw full text.

    Returns:
        ``CompletenessResult`` on every successful LLM judgement.
        ``None`` iff all retries exhausted — per Failure Contract
        (§1): technical failure is signalled by ``None``, not by a
        fake ``INCOMPLETE`` status that would silently route the
        source to the skip-cache.
    """
    template = _resolve_completeness_template(project_root)
    evidence_pack, _meta = _build_evidence_pack(
        content, structural_summary, fingerprint="checker-v7",
    )
    system_prompt, user_prompt = render_prompt(template, {
        "text": content,
        "evidence_pack": evidence_pack,
        "doc_type_hint": doc_type_hint,
        "content_limit": str(EVIDENCE_PACK_BUDGET_BYTES),
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