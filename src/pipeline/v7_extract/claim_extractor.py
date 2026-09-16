"""Stage 5A of the V7 extract pipeline: evidence-backed claim extraction.

Task 15 (plan 2026-09-17 v7-stage-remediation-master-plan).

Invariant (the whole point of this stage): **the LLM never emits byte
offsets**. It sees the script-generated candidate spans (span id +
deterministic excerpt taken from ``source_bytes``) and cites the span ids
it used. This module maps ``span_id`` → ``CanonicalSpan`` → the
SOURCE-ABSOLUTE byte range carried by that span, so every ``EvidenceRef``
is derived by the script and can be re-verified against the original
bytes (``EvidenceRef.excerpt_from``).

Consequences the caller may rely on:

  * A fabricated span id cannot produce evidence — the ref is dropped
    (never raised), and a claim left with zero refs is reported as
    ``ClaimSupport.INSUFFICIENT_EVIDENCE`` rather than silently accepted.
  * ``claim_id`` is script-generated and deterministic — the LLM has no
    way to collide two claims or to smuggle identity through it.
  * Technical failure (LLM error / unparseable JSON / schema violation on
    every attempt) raises ``RuntimeError`` per Failure Contract §1.3: a
    technical failure must never be disguised as "this slot has no
    claims" (``NOT_APPLICABLE``).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .canonical_spans import CanonicalSpan
from .claim import Claim, ClaimRisk, ClaimSupport, EvidenceRef
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


# Task 15: hard cap on how many claims one slot may contribute to a page.
MAX_CLAIMS_PER_SLOT = 6

# Prompt kind of the Stage 5A prompt (distinct from the legacy
# ``fill_slots`` prompt — Task 18 does the rewire, so both must coexist).
PROMPT_KIND = "fill_slots_extract"


# ---------------------------------------------------------------------------
# Risk assessment (script-owned, deterministic)
# ---------------------------------------------------------------------------

# Task 15: claims that silently flip meaning when lightly reworded get
# flagged HIGH so Task 17's semantic reviewer spends its budget where it
# matters. Deliberately EXCLUDES the bare copulas 是 / 为 — they appear in
# nearly every definitional sentence ("RAG 是一种…"), so flagging them
# would make the HIGH set economically useless.
_RISK_PATTERNS: tuple[re.Pattern[str], ...] = (
    # numbers / percentages / multiples
    re.compile(r"\d+(\.\d+)?\s*%"),
    re.compile(r"\d+(\.\d+)?\s*倍"),
    # magnitude-of-change verbs
    re.compile(r"提高|降低|增加|减少|提升|下降|增长|缩小|放大"),
    # applicability
    re.compile(r"适合|不适合|适用于|不适用|只适合|仅适合"),
    # causality
    re.compile(r"导致|引起|造成|引发|由于|因为|因此"),
    # comparison
    re.compile(r"优于|劣于|好于|差于|强于|弱于|相当于|高于|低于"),
    # explicit negation (NOT the bare copula)
    re.compile(r"不是|并非|不能|无法|不应|不需要|不同于"),
)


def assess_claim_risk(text: str) -> ClaimRisk:
    """``ClaimRisk.HIGH`` iff *text* matches any high-risk pattern."""
    for pattern in _RISK_PATTERNS:
        if pattern.search(text):
            return ClaimRisk.HIGH
    return ClaimRisk.LOW


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@dataclass
class SlotExtraction:
    """Stage 5A output: one slot → 0..N evidence-backed claims.

    ``status`` is the slot-level rollup of ``claims[].support``:

      * no claims at all          → NOT_APPLICABLE
      * every claim lacks valid evidence → INSUFFICIENT_EVIDENCE
      * otherwise                 → SUPPORTED

    Conflict detection is NOT this stage's job (Task 16/17).
    """

    slot_name: str
    claims: list[Claim] = field(default_factory=list)
    status: ClaimSupport = ClaimSupport.NOT_APPLICABLE


async def extract_slot_claims(
    slot_name: str,
    *,
    topic_label: str,
    spans: list[CanonicalSpan],
    llm: LLMClient,
    project_root: Path | str | None = None,
    source_bytes: bytes,
    max_retries: int = 3,
) -> SlotExtraction:
    """Stage 5A: one slot → 0..N evidence-backed claims.

    The LLM sees the candidate spans (id + deterministic excerpt) and
    returns claims citing ``span_ids``. It NEVER returns byte offsets or
    excerpts. Raises ``RuntimeError`` when all retries are exhausted
    (technical failure — the caller maps that to FAILED, per Failure
    Contract §1.3).
    """
    template = _resolve_claim_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "slot_name": slot_name,
        "topic_label": topic_label,
        "spans_text": _render_spans(spans, source_bytes),
        "max_claims": str(MAX_CLAIMS_PER_SLOT),
    })

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
            claims = _payload_to_claims(
                payload, slot_name=slot_name, spans=spans,
            )
            return SlotExtraction(
                slot_name=slot_name,
                claims=claims,
                status=_rollup_status(claims),
            )
        except LLMResponseError as e:
            last_error = e
            log.info(
                "extract_slot_claims[%s/%s]: response failed validation "
                "(attempt %d/%d): %s",
                topic_label, slot_name, attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "extract_slot_claims[%s/%s]: LLM call failed (attempt %d/%d): %s",
                topic_label, slot_name, attempt + 1, max_retries, e,
            )
            continue

    raise RuntimeError(
        f"Stage 5A claim extraction failed for slot {slot_name!r} "
        f"(topic {topic_label!r}) after {max_retries} attempts. "
        f"last_error={last_error!r}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_spans(spans: list[CanonicalSpan], source_bytes: bytes) -> str:
    """Render the candidate span list the LLM cites by ``span_id``.

    Excerpts are sliced straight out of ``source_bytes`` (the same
    derivation ``EvidenceRef.excerpt_from`` uses) — never from LLM text,
    and never truncated, since spans are already bounded by
    ``SPAN_TARGET_BYTES``.
    """
    blocks: list[str] = []
    for span in spans:
        excerpt = source_bytes[span.start_byte:span.end_byte].decode(
            "utf-8", errors="replace"
        )
        blocks.append(f"=== {span.span_id} ===\n{excerpt}")
    return "\n\n".join(blocks)


def _payload_to_claims(
    payload: dict[str, Any],
    *,
    slot_name: str,
    spans: list[CanonicalSpan],
) -> list[Claim]:
    """Translate the LLM JSON payload into script-verified ``Claim`` objects.

    Parsing rules (all script-owned):
      1. unknown ``span_ids`` are dropped, not raised;
      2. ``span_id`` → index in *spans* populates ``EvidenceRef`` byte range;
      3. non-substantive claim text is skipped;
      4. identical text within a slot is deduped (first wins);
      5. output is capped at ``MAX_CLAIMS_PER_SLOT``.
    """
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list):
        return []

    by_id = {span.span_id: (index, span) for index, span in enumerate(spans)}

    claims: list[Claim] = []
    seen_text: set[str] = set()

    for entry in raw_claims:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text or text in seen_text:
            continue

        refs = _evidence_refs(entry.get("span_ids"), by_id)
        claim = Claim(
            claim_id="",  # filled in below, once the claim is accepted
            slot_name=slot_name,
            text=text,
            evidence_refs=refs,
            support=(
                ClaimSupport.SUPPORTED
                if refs
                else ClaimSupport.INSUFFICIENT_EVIDENCE
            ),
            confidence=_confidence(entry.get("confidence")),
            risk=assess_claim_risk(text),
        )
        if not claim.is_substantive():  # placeholder / whitespace-only (rule 3)
            continue

        claim.claim_id = _claim_id(slot_name, len(claims), text, refs)
        seen_text.add(text)
        claims.append(claim)
        if len(claims) >= MAX_CLAIMS_PER_SLOT:
            break

    return claims


def _evidence_refs(
    raw_span_ids: Any,
    by_id: dict[str, tuple[int, CanonicalSpan]],
) -> list[EvidenceRef]:
    """Map LLM-cited ``span_ids`` to canonical byte ranges.

    Unknown ids are dropped silently (rule 1) — a hallucinated span id is
    a real LLM failure mode that must degrade to "no evidence", not crash
    the stage. Duplicate ids collapse to one ref.
    """
    if not isinstance(raw_span_ids, list):
        return []

    refs: list[EvidenceRef] = []
    used: set[str] = set()
    for raw_id in raw_span_ids:
        if not isinstance(raw_id, str):
            continue
        span_id = raw_id.strip()
        if span_id in used:
            continue
        mapped = by_id.get(span_id)
        if mapped is None:
            log.info("dropping unknown span_id cited by LLM: %r", span_id)
            continue
        used.add(span_id)
        index, span = mapped
        refs.append(
            EvidenceRef(
                item_id=span.item_id,
                item_index=span.item_index,
                span_index=index,
                start_byte=span.start_byte,
                end_byte=span.end_byte,
            )
        )
    return refs


def _claim_id(
    slot_name: str,
    local_index: int,
    text: str,
    refs: list[EvidenceRef],
) -> str:
    """Script-generated deterministic id — never derived from LLM-supplied ids.

    ``claim-{sha1(slot_name|local_index|text|sorted(span_ids))[:12]}``
    """
    span_ids = sorted(
        f"{ref.item_id}:{ref.start_byte}-{ref.end_byte}" for ref in refs
    )
    identity = f"{slot_name}|{local_index}|{text}|{','.join(span_ids)}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"claim-{digest}"


def _confidence(raw: Any) -> float:
    """Clamp the LLM's self-reported confidence into [0, 1]; else 0.0."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    return min(1.0, max(0.0, float(raw)))


def _rollup_status(claims: list[Claim]) -> ClaimSupport:
    """Slot-level rollup (Task 15): see ``SlotExtraction`` docstring."""
    if not claims:
        return ClaimSupport.NOT_APPLICABLE
    if all(c.support is ClaimSupport.INSUFFICIENT_EVIDENCE for c in claims):
        return ClaimSupport.INSUFFICIENT_EVIDENCE
    return ClaimSupport.SUPPORTED


def _resolve_claim_template(
    project_root: Path | str | None,
) -> "PromptTemplate":
    """Resolve the Stage 5A prompt; raise RuntimeError on config error."""
    try:
        return resolve(PROMPT_KIND, project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 {PROMPT_KIND} prompt is not available: {e}. Check that "
            f"prompts/builtin/{PROMPT_KIND}.toml is installed."
        ) from e


__all__ = [
    "MAX_CLAIMS_PER_SLOT",
    "PROMPT_KIND",
    "SlotExtraction",
    "assess_claim_risk",
    "extract_slot_claims",
]
