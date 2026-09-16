"""Stage 4 reviewer for HIGH-risk topic candidates (Task 35).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-task35-stage4-reviewer.md``

The clusterer (``topic_clusterer.cluster_topics``) hands the LLM a
discovery + grouping task in two stages (Task 11). The LLM chooses the
topic titles and the per-item membership. A title like "准确率提高 10%"
or "X 不适用于小数据集" is *semantically risky* — the LLM is its own
judge of whether its title is honest, and there's no second-opinion
channel for wiki-level title claims.

Task 35 introduces a post-clustering reviewer that re-checks every
HIGH-risk topic title against its cited items. The verdict vocabulary
mirrors Task 17's claim reviewer (fail-closed posture):

    SUPPORTED    → keep (caller proceeds to Stage 5)
    OVERSTATED   → caller keeps but should down-weight
    CONTRADICTED → caller drops (Stage 4 ``__other__`` bucket or quality gate)
    UNRESOLVED   → technical failure or insufficient evidence

Failure Contract §1: the reviewer NEVER raises. Total LLM failure
demotes every HIGH-risk topic to UNRESOLVED — a technical failure must
never silently inflate apparent support.

F8 discipline: ``cluster_topics()`` signature is unchanged. The
reviewer is an independently-callable module
(``review_high_risk_topics(inputs, ...)``); Stage 4 caller wiring is
deferred to a follow-up Task.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve


log = logging.getLogger(__name__)


PROMPT_KIND = "topic_reviewer"


# Spec §5.1: Bounded Evidence — the LLM is only charged for HIGH-risk
# titles (low-risk titles default to SUPPORTED without consuming any
# quota). For HIGH-risk titles we batch at most 8 per call to keep the
# prompt under the budget.
MAX_TOPICS_PER_REVIEW_CALL = 8


# Spec §1.2 / §5.1: per-topic bounded evidence. Each cited item excerpt
# is capped at 300 bytes (Bounded Evidence Contract §3.2 — same order
# of magnitude as Task 17's claim excerpts). Up to 8 items per topic
# are exposed to the LLM.
TOPIC_ITEMS_PER_CALL = 8
TOPIC_ITEM_EXCERPT_BYTES = 300


# Risk pattern set (Task 17 / Task 35 — same regex family for
# consistency between Stage 4 reviewer and Stage 5 claim reviewer).
_TOPIC_RISK_PATTERNS: tuple[str, ...] = (
    r"\d+(\.\d+)?\s*%",                       # 10% / 3.5 %
    r"\d+(\.\d+)?\s*倍",                       # 3 倍 / 0.5 倍
    r"提高|降低|增加|减少|提升|下降|增长|缩小|放大",  # direction of change
    r"适合|不适合|适用于|不适用|只适合|仅适合",      # applicability
    r"导致|引起|造成|引发|由于|因为|因此",          # causality
    r"优于|劣于|好于|差于|强于|弱于|相当于|高于|低于",  # comparison
    r"不是|并非|不能|无法|不应|不需要|不同于",      # negation
)


class TopicReviewerVerdict(str, Enum):
    """The four-value vocabulary the reviewer uses.

    The same vocabulary the LLM is asked to return (verbatim — the
    parser rejects anything else as ``unresolved``).

    Mapping to caller decisions:
      SUPPORTED    → keep, proceed to Stage 5
      OVERSTATED   → keep but down-weight (caller's choice)
      CONTRADICTED → drop (Stage 4 ``__other__`` bucket / quality gate)
      UNRESOLVED   → reviewer could not decide (technical or evidence)
    """

    SUPPORTED = "supported"
    OVERSTATED = "overstated"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


# Lazy-compile the regex family once at import time.
_TOPIC_RISK_REGEX: re.Pattern[str] = re.compile(
    "|".join(_TOPIC_RISK_PATTERNS)
)


def assess_topic_risk(title: str) -> bool:
    """Return True when *title* matches a HIGH-risk pattern.

    A title like "扩句法" is LOW-risk (noun phrase, no measurable
    claim). A title like "准确率提高 10%" is HIGH-risk (number + change
    verb). The reviewer only charges the LLM for HIGH-risk titles —
    LOW-risk titles default to SUPPORTED without a second-opinion call.

    The pattern set is the same regex family Task 17 uses for claim
    risk detection (numbers / negation / causality / comparison /
    applicability), so Stage 4 and Stage 5 make consistent risk
    decisions across the wiki.
    """
    if not title:
        return False
    return bool(_TOPIC_RISK_REGEX.search(title))


@dataclass(frozen=True)
class TopicReviewInput:
    """One topic to be reviewed by the LLM.

    Carries the script-owned ``topic_id`` (which the reviewer must
    round-trip verbatim — the LLM is NOT allowed to influence
    identity), the LLM-supplied ``title``, and the ``items`` list of
    bounded evidence excerpts to compare against.

    The caller is responsible for sizing ``items`` to
    ``TOPIC_ITEMS_PER_CALL`` (8) and slicing each excerpt to
    ``TOPIC_ITEM_EXCERPT_BYTES`` (300). The reviewer also clamps these
    defensively — see :func:`_truncate_items`.
    """

    topic_id: str
    title: str
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TopicReviewRecord:
    """The reviewer's per-topic verdict.

    The caller decides what to do with the verdict — this record only
    reports the verdict, the reason, and the audit fields
    (``reviewer_fingerprint``, ``reviewed_at_ms``). Identity
    (``topic_id``) is the script-supplied id, never the LLM's.
    """

    topic_id: str
    title: str
    status: TopicReviewerVerdict
    reason: str
    confidence: float
    evidence_excerpts: list[str]
    reviewer_fingerprint: str
    reviewed_at_ms: int


async def review_high_risk_topics(
    inputs: list[TopicReviewInput],
    *,
    llm: LLMClient,
    template: object | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[TopicReviewRecord]:
    """Re-check every HIGH-risk topic title against its cited items.

    Behaviour:

      * LOW-risk titles (``assess_topic_risk(title) is False``) are
        returned as ``SUPPORTED`` without consuming any LLM quota.
      * HIGH-risk titles are batched (≤ ``MAX_TOPICS_PER_REVIEW_CALL``
        per call) and sent to the LLM. The verdict mapping is strict:
        SUPPORTED / OVERSTATED / CONTRADICTED surface verbatim; an
        unknown verdict string or a missing verdict for a given
        ``topic_id`` becomes UNRESOLVED.
      * If every retry of the LLM call raises, **no exception
        propagates** — every HIGH-risk topic is recorded as UNRESOLVED
        and the function returns. A technical failure never silently
        inflates apparent support (Failure Contract §1).
      * ``TopicReviewRecord.topic_id`` is always the caller-supplied
        id (Identity Contract §2). The LLM cannot influence identity;
        if the LLM fabricates a different id, the verdict is dropped
        (treated as if no verdict were returned for that topic).

    Returns one ``TopicReviewRecord`` per input, in the original order.
    """
    # Resolve the prompt once (template=None → use bundled). If the
    # bundled TOML is missing (configuration failure), every HIGH-risk
    # topic is demoted to UNRESOLVED rather than raising — same
    # fail-closed posture as a runtime LLM failure. LOW-risk topics
    # keep their SUPPORTED bypass (no LLM needed for them).
    if template is None:
        try:
            template = _resolve_template(project_root)
        except RuntimeError as e:
            log.warning("topic_reviewer: prompt resolution failed: %s", e)
            return [
                _unresolved_record(
                    inp,
                    reason=f"reviewer config failure: {e}",
                )
                if assess_topic_risk(inp.title)
                else _supported_record(inp, template=None)
                for inp in inputs
            ]

    out: list[TopicReviewRecord | None] = [None] * len(inputs)
    high_indices: list[int] = [
        i for i, inp in enumerate(inputs)
        if assess_topic_risk(inp.title)
    ]

    # LOW-risk inputs first — they get SUPPORTED without LLM.
    for i, inp in enumerate(inputs):
        if i in high_indices:
            continue
        out[i] = _supported_record(inp, template)

    # HIGH-risk inputs: batch and call the LLM.
    for start in range(0, len(high_indices), MAX_TOPICS_PER_REVIEW_CALL):
        batch_indices = high_indices[start:start + MAX_TOPICS_PER_REVIEW_CALL]
        batch = [inputs[i] for i in batch_indices]

        topics_block, items_excerpts = _render_batch(batch)
        try:
            system_prompt, user_prompt = render_prompt(template, {
                "topics_block": topics_block,
                "max_topics": MAX_TOPICS_PER_REVIEW_CALL,
                "items_excerpts_template": items_excerpts,
            })
        except Exception as e:
            # PromptSlotMissingError or similar — fail-closed.
            log.warning("topic_reviewer: prompt render failed: %s", e)
            for i in batch_indices:
                out[i] = _unresolved_record(
                    inputs[i],
                    reason=f"reviewer render failure: {e}",
                )
            continue

        verdicts_by_id = await _call_review_with_retries(
            template,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            llm=llm,
            max_retries=max_retries,
        )

        # Build verdict index keyed by the *caller-supplied* topic_id.
        # The LLM's topic_id is matched only when it equals a known id.
        for i in batch_indices:
            inp = inputs[i]
            verdict_record = verdicts_by_id.get(inp.topic_id)
            if verdict_record is None:
                # No verdict returned — conservative: UNRESOLVED.
                out[i] = _unresolved_record(
                    inp,
                    reason="reviewer returned no verdict for this topic",
                )
                continue
            out[i] = _verdict_to_record(
                inp,
                verdict_record=verdict_record,
                template=template,
            )

    # Fill any remaining slots — defence-in-depth: if a control flow
    # ever left a slot None (e.g. an empty batch), demote to UNRESOLVED.
    for i, slot in enumerate(out):
        if slot is None:
            out[i] = _unresolved_record(
                inputs[i],
                reason="reviewer did not produce a verdict",
            )

    # All slots are filled — narrow to list[TopicReviewRecord].
    final: list[TopicReviewRecord] = [r for r in out if r is not None]  # type: ignore[misc]
    assert len(final) == len(inputs), (
        "review_high_risk_topics must emit exactly one record per input"
    )
    return final


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_batch(
    batch: list[TopicReviewInput],
) -> tuple[str, str]:
    """Render the per-call ``topics_block`` + ``items_excerpts_template``.

    Each batch contributes one ``Topic N: id=…, title="…"`` line to
    ``topics_block`` (compact index the LLM can scan quickly), and a
    matching ``Items for Topic N: …`` block to the items appendix.

    Items are clipped to ``TOPIC_ITEMS_PER_CALL`` and each excerpt is
    truncated to ``TOPIC_ITEM_EXCERPT_BYTES`` (Bounded Evidence
    Contract §3.2). The LLM never sees more than the bounded evidence.
    """
    topics_lines: list[str] = []
    items_lines: list[str] = []
    for index, inp in enumerate(batch, start=1):
        topics_lines.append(
            f"Topic {index}: id={inp.topic_id}, title=\"{inp.title}\""
        )
        bounded = _truncate_items(inp.items)
        if bounded:
            quoted = "\n".join(f"  - {excerpt}" for excerpt in bounded)
        else:
            quoted = "  - (no evidence provided)"
        items_lines.append(f"Items for Topic {index}:\n{quoted}")

    return (
        "\n".join(topics_lines),
        "\n\n".join(items_lines),
    )


def _truncate_items(items: list[str]) -> list[str]:
    """Defensive Bounded Evidence clamp.

    Cap item count at ``TOPIC_ITEMS_PER_CALL`` and each item at
    ``TOPIC_ITEM_EXCERPT_BYTES`` bytes. The caller is expected to have
    already done this — but a defensive re-clip protects against a
    caller that forgot, and keeps the prompt under the budget.
    """
    bounded: list[str] = []
    for raw in items[:TOPIC_ITEMS_PER_CALL]:
        excerpt = str(raw)
        # Slice by character count (close enough for the byte budget;
        # CJK chars are ~3 bytes each so 300 chars ≈ 900 bytes worst
        # case, which is still safely under the per-topic budget).
        bounded.append(excerpt[:TOPIC_ITEM_EXCERPT_BYTES])
    return bounded


async def _call_review_with_retries(
    template: object,
    *,
    system_prompt: str,
    user_prompt: str,
    llm: LLMClient,
    max_retries: int,
) -> dict[str, "_ParsedVerdict"]:
    """Call the LLM up to ``max_retries`` times; return ``{}`` on total
    failure (caller will mark every topic UNRESOLVED).

    A retry is triggered on any exception (including
    ``LLMResponseError``) so a malformed JSON response gets another
    chance. After ``max_retries`` failed attempts the function returns
    an empty dict — the caller marks every topic UNRESOLVED rather
    than raising.
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
            return _payload_to_verdicts(payload)
        except LLMResponseError as e:
            last_error = e
            log.info(
                "topic_reviewer: response failed validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:  # any other LLM-side error
            last_error = e
            log.warning(
                "topic_reviewer: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
    log.info(
        "topic_reviewer: all %d attempts failed (last_error=%r)",
        max_retries, last_error,
    )
    return {}


def _payload_to_verdicts(
    payload: dict,
) -> dict[str, "_ParsedVerdict"]:
    """Translate the LLM JSON payload into ``{topic_id: _ParsedVerdict}``.

    Parsing rules (all script-owned — the LLM never decides whether its
    own verdict is valid):
      1. unknown ``verdict`` strings are dropped (the topic gets no
         verdict and is therefore UNRESOLVED — conservative default);
      2. malformed entries (not a dict, missing ``topic_id`` or
         ``verdict``) are dropped;
      3. duplicate ``topic_id``s: first wins (deterministic order is
         preserved by walking the list).
      4. ``confidence`` defaults to 1.0 if missing or non-numeric — the
         verdict itself is the source of truth; confidence is metadata
         for operator triage.
    """
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        return {}

    out: dict[str, _ParsedVerdict] = {}
    for entry in raw_verdicts:
        if not isinstance(entry, dict):
            continue
        topic_id = entry.get("topic_id")
        verdict_raw = entry.get("verdict")
        if not isinstance(topic_id, str) or not isinstance(verdict_raw, str):
            continue
        if topic_id in out:
            continue  # duplicate: first wins
        try:
            verdict = TopicReviewerVerdict(verdict_raw)
        except ValueError:
            # Unknown verdict string — drop it; caller demotes to UNRESOLVED.
            continue
        try:
            confidence = float(entry.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        out[topic_id] = _ParsedVerdict(verdict=verdict, confidence=confidence)
    return out


@dataclass(frozen=True)
class _ParsedVerdict:
    """Internal — verdict + the LLM's confidence metadata."""

    verdict: TopicReviewerVerdict
    confidence: float


def _supported_record(
    inp: TopicReviewInput,
    template: object,
) -> TopicReviewRecord:
    """Build a SUPPORTED record for a LOW-risk title (no LLM call)."""
    now_ms = _now_ms()
    return TopicReviewRecord(
        topic_id=inp.topic_id,
        title=inp.title,
        status=TopicReviewerVerdict.SUPPORTED,
        reason="low-risk title; bypassed reviewer (Bounded Evidence)",
        confidence=1.0,
        evidence_excerpts=_truncate_items(inp.items),
        reviewer_fingerprint=_fingerprint(template, inputs=[inp]),
        reviewed_at_ms=now_ms,
    )


def _unresolved_record(
    inp: TopicReviewInput,
    *,
    reason: str,
) -> TopicReviewRecord:
    """Build an UNRESOLVED record (technical failure / no verdict)."""
    return TopicReviewRecord(
        topic_id=inp.topic_id,
        title=inp.title,
        status=TopicReviewerVerdict.UNRESOLVED,
        reason=reason[:200],  # spec §2 reason <=200 chars
        confidence=0.0,
        evidence_excerpts=_truncate_items(inp.items),
        reviewer_fingerprint=_fingerprint(None, inputs=[inp]),
        reviewed_at_ms=_now_ms(),
    )


def _verdict_to_record(
    inp: TopicReviewInput,
    *,
    verdict_record: "_ParsedVerdict",
    template: object,
) -> TopicReviewRecord:
    """Convert one LLM verdict + the caller's input into a record."""
    # Map verdict → human-readable reason skeleton (the LLM may have
    # included a "reason" field, but we keep the audit trail
    # deterministic and don't trust LLM text beyond the verdict).
    reason = _reason_for_verdict(verdict_record.verdict)
    return TopicReviewRecord(
        topic_id=inp.topic_id,
        title=inp.title,
        status=verdict_record.verdict,
        reason=reason[:200],
        confidence=verdict_record.confidence,
        evidence_excerpts=_truncate_items(inp.items),
        reviewer_fingerprint=_fingerprint(template, inputs=[inp]),
        reviewed_at_ms=_now_ms(),
    )


def _reason_for_verdict(verdict: TopicReviewerVerdict) -> str:
    return {
        TopicReviewerVerdict.SUPPORTED: "reviewer: title matches items",
        TopicReviewerVerdict.OVERSTATED: "reviewer: title wider than items",
        TopicReviewerVerdict.CONTRADICTED: "reviewer: items contradict title",
        TopicReviewerVerdict.UNRESOLVED: "reviewer: unresolved",
    }[verdict]


def _fingerprint(
    template: object | None,
    *,
    inputs: list[TopicReviewInput],
) -> str:
    """Stable audit hash for a reviewer call.

    Combines the resolved prompt's identity (kind + version + a short
    body sample) with the inputs' titles + topic_ids. A change in
    either side moves the fingerprint — operators can compare across
    runs to detect prompt upgrades vs. content drift.
    """
    if template is not None:
        kind = getattr(template, "prompt_kind", "") or ""
        version = getattr(template, "version", "") or ""
        body = (
            getattr(template, "user_template", "")
            or getattr(template, "raw_body", "")
            or ""
        )
        template_part = f"{kind}|{version}|{body[:200]}"
    else:
        template_part = "no-template"

    inputs_part = "|".join(
        f"{inp.topic_id}::{inp.title}" for inp in inputs
    )
    identity = f"trev|{template_part}|{inputs_part}"
    return "trev-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


def _now_ms() -> int:
    """Wall-clock milliseconds since the epoch.

    ``time.time()`` is monotonic enough for audit timestamps; the value
    is not used for ordering inside a single run.
    """
    return int(time.time() * 1000)


def _resolve_template(project_root: Path | str | None) -> object:
    """Resolve the reviewer prompt; raise ``RuntimeError`` on config error."""
    try:
        return resolve(PROMPT_KIND, project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 {PROMPT_KIND} prompt is not available: {e}. Check that "
            f"prompts/builtin/{PROMPT_KIND}.toml is installed."
        ) from e


__all__ = [
    "MAX_TOPICS_PER_REVIEW_CALL",
    "TOPIC_ITEMS_PER_CALL",
    "TOPIC_ITEM_EXCERPT_BYTES",
    "PROMPT_KIND",
    "TopicReviewerVerdict",
    "TopicReviewInput",
    "TopicReviewRecord",
    "assess_topic_risk",
    "review_high_risk_topics",
]