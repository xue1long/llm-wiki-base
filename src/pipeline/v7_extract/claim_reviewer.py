"""Stage 5B semantic reviewer for HIGH-risk claims (Task 17).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md``
Task 17 (Stage 5 — Semantic reviewer, high-risk claims).

Design rule (mirror of Task 15's): **the LLM never decides whether its own
evidence is valid** for the verdict vocabulary, but for HIGH-risk claims
(numbers / negation / causality / comparison / applicability) we *do* ask
it to re-check the claim against the deterministic excerpt. The verdict
mapping is fail-closed:

  SUPPORTED    → keep ``ClaimSupport.SUPPORTED``
  CONTRADICTED → ``INSUFFICIENT_EVIDENCE`` (filter_substantive_claims drops)
  INSUFFICIENT → ``INSUFFICIENT_EVIDENCE``
  AMBIGUOUS    → ``INSUFFICIENT_EVIDENCE``

Reviewer-level failure (all ``max_retries`` attempts raise) demotes every
HIGH-risk claim to ``INSUFFICIENT_EVIDENCE`` rather than raising — a
technical failure must never silently inflate apparent support
(Failure Contract §1).

Bounded Evidence Contract §3.2: each HIGH-risk claim's prompt block is the
cited deterministic excerpts only (``source_bytes[ref.start_byte:ref.end_byte]``),
capped at ``MAX_EVIDENCE_BYTES`` (3000). LOW-risk claims bypass the LLM
entirely — they are not seen, not cited, not charged.
"""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from .claim import Claim, ClaimRisk, ClaimSupport
from .claim_validator import MAX_EVIDENCE_BYTES
from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve


log = logging.getLogger(__name__)


PROMPT_KIND = "claim_reviewer"


class ReviewerVerdict(str, Enum):
    """The four-value vocabulary the LLM is allowed to return.

    Anything outside this set is treated as ``INSUFFICIENT`` (the
    conservative default) and demotes the claim.
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    AMBIGUOUS = "ambiguous"


_VERDICT_TO_SUPPORT: dict[ReviewerVerdict, ClaimSupport] = {
    # The whole point of the reviewer is to be cheap to *keep* and
    # expensive to *demote*: SUPPORTED is the only verdict that leaves
    # ClaimSupport.SUPPORTED alone.
    ReviewerVerdict.SUPPORTED: ClaimSupport.SUPPORTED,
    ReviewerVerdict.CONTRADICTED: ClaimSupport.INSUFFICIENT_EVIDENCE,
    ReviewerVerdict.INSUFFICIENT: ClaimSupport.INSUFFICIENT_EVIDENCE,
    ReviewerVerdict.AMBIGUOUS: ClaimSupport.INSUFFICIENT_EVIDENCE,
}


async def review_high_risk_claims(
    claims: list[Claim],
    *,
    source_bytes: bytes,
    llm: LLMClient,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[Claim]:
    """Re-check every HIGH-risk claim against its cited evidence.

    Behaviour:
      * Only ``claim.risk is ClaimRisk.HIGH`` claims are sent to the LLM.
      * LOW-risk claims are returned verbatim (``support`` unchanged).
      * The verdict mapping is fail-closed: only ``SUPPORTED`` keeps
        ``ClaimSupport.SUPPORTED``; every other verdict demotes the claim
        to ``ClaimSupport.INSUFFICIENT_EVIDENCE`` so the
        ``filter_substantive_claims`` rendering gate drops it.
      * If every retry of the LLM call raises, **no exception propagates**
        — every HIGH-risk claim is demoted to ``INSUFFICIENT_EVIDENCE``
        and the function returns. A technical failure never silently
        inflates apparent support (Failure Contract §1).

    Returns the *same* list object (in-place mutation), and also returns
    it for caller convenience.
    """
    high_risk = [claim for claim in claims if claim.risk is ClaimRisk.HIGH]
    if not high_risk:
        return claims

    try:
        template = _resolve_template(project_root)
    except RuntimeError as e:
        # Prompt resolution is a configuration failure — same fail-closed
        # posture as a runtime LLM failure: demote, log, return.
        log.warning("claim_reviewer: prompt resolution failed: %s", e)
        _demote_all(high_risk)
        return claims

    system_prompt, user_prompt = render_prompt(template, {
        "claims_block": _render_claims_block(high_risk, source_bytes),
    })

    verdicts_by_id = await _call_review_with_retries(
        template, system_prompt=system_prompt, user_prompt=user_prompt,
        llm=llm, max_retries=max_retries,
    )

    if verdicts_by_id is None:
        # All retries exhausted — fail-closed demote.
        log.warning(
            "claim_reviewer: LLM failed after %d attempts; demoting %d "
            "HIGH-risk claim(s) to INSUFFICIENT_EVIDENCE",
            max_retries, len(high_risk),
        )
        _demote_all(high_risk)
        return claims

    known_ids = {claim.claim_id for claim in high_risk}
    for claim in high_risk:
        verdict = verdicts_by_id.get(claim.claim_id)
        if verdict is None:
            # No verdict for this claim — treat as insufficient
            # (conservative: no reviewer signal -> don't keep SUPPORTED).
            claim.support = ClaimSupport.INSUFFICIENT_EVIDENCE
            continue
        claim.support = _VERDICT_TO_SUPPORT[verdict]
    return claims


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_claims_block(claims: list[Claim], source_bytes: bytes) -> str:
    """Render the HIGH-risk claims + their cited excerpts.

    Bounded Evidence Contract §3.2: each cited excerpt is the deterministic
    slice ``source_bytes[ref.start_byte:ref.end_byte]`` capped at
    ``MAX_EVIDENCE_BYTES`` (3000) — the LLM never sees more than the
    single cited span for any given ref.
    """
    blocks: list[str] = []
    for claim in claims:
        evidence_lines: list[str] = []
        for ref in claim.evidence_refs:
            end = min(ref.end_byte, ref.start_byte + MAX_EVIDENCE_BYTES)
            excerpt = source_bytes[ref.start_byte:end].decode(
                "utf-8", errors="replace",
            )
            evidence_lines.append(f"  - [{ref.item_id}] {excerpt}")
        evidence_block = "\n".join(evidence_lines) if evidence_lines else "  - (no evidence)"
        blocks.append(
            f"=== {claim.claim_id} ===\nCLAIM: {claim.text}\nEVIDENCE:\n{evidence_block}"
        )
    return "\n\n".join(blocks)


async def _call_review_with_retries(
    template,
    *,
    system_prompt: str,
    user_prompt: str,
    llm: LLMClient,
    max_retries: int,
) -> dict[str, ReviewerVerdict] | None:
    """Call the LLM up to ``max_retries`` times; return ``None`` on total
    failure (caller will fail-closed demote).

    A retry is triggered on any ``Exception`` (including ``LLMResponseError``)
    so that a malformed JSON response gets another chance. After
    ``max_retries`` failed attempts the function returns ``None`` — the
    caller demotes rather than raises.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind=PROMPT_KIND,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=2048,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            verdicts = _payload_to_verdicts(payload)
            return verdicts
        except LLMResponseError as e:
            last_error = e
            log.info(
                "claim_reviewer: response failed validation (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:  # any other LLM-side error (timeout, rate-limit, ...)
            last_error = e
            log.warning(
                "claim_reviewer: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
    log.info(
        "claim_reviewer: all %d attempts failed (last_error=%r)",
        max_retries, last_error,
    )
    return None


def _payload_to_verdicts(
    payload: dict,
) -> dict[str, ReviewerVerdict]:
    """Translate the LLM JSON payload into ``{claim_id: ReviewerVerdict}``.

    Parsing rules (all script-owned — the LLM never decides whether its
    own verdict is valid):
      1. unknown ``verdict`` values are dropped (the claim gets no verdict
         and is therefore demoted — conservative default);
      2. malformed entries (not a dict, missing ``claim_id``/``verdict``)
         are dropped;
      3. duplicate ``claim_id``s: first wins (deterministic order is
         preserved by walking the list).
    """
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        return {}

    out: dict[str, ReviewerVerdict] = {}
    for entry in raw_verdicts:
        if not isinstance(entry, dict):
            continue
        claim_id = entry.get("claim_id")
        verdict_raw = entry.get("verdict")
        if not isinstance(claim_id, str) or not isinstance(verdict_raw, str):
            continue
        if claim_id in out:
            continue  # duplicate: first wins
        try:
            verdict = ReviewerVerdict(verdict_raw)
        except ValueError:
            # Unknown verdict string — treat as if no verdict were
            # returned (claim will be demoted by caller).
            continue
        out[claim_id] = verdict
    return out


def _demote_all(claims: list[Claim]) -> None:
    """Demote every claim in *claims* to ``INSUFFICIENT_EVIDENCE`` in-place."""
    for claim in claims:
        claim.support = ClaimSupport.INSUFFICIENT_EVIDENCE


def _resolve_template(project_root: Path | str | None):
    """Resolve the reviewer prompt; raise ``RuntimeError`` on config error."""
    try:
        return resolve(PROMPT_KIND, project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 {PROMPT_KIND} prompt is not available: {e}. Check that "
            f"prompts/builtin/{PROMPT_KIND}.toml is installed."
        ) from e


__all__ = [
    "PROMPT_KIND",
    "ReviewerVerdict",
    "review_high_risk_claims",
]