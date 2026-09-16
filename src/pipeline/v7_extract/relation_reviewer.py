"""Stage 6R semantic reviewer for HIGH-risk relations (Task 36).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-task36-stage6r-reviewer.md``

The Stage 6R ``RelationAssertion`` produced by ``relation_extractor``
may have a HIGH-risk predicate (``CAUSES`` / ``REQUIRES`` /
``CONTRADICTS`` / ``DEPENDS_ON`` / ``EXTENDS`` / ``BROADER`` /
``NARROWER``). For those relations we ask the LLM to re-check the
semantic honesty of the relation against the cited evidence. The
verdict vocabulary mirrors Task 17 (claim reviewer) and Task 35
(topic reviewer):

    SUPPORTED    → caller keeps the relation
    OVERSTATED   → caller keeps but should down-weight
    CONTRADICTED → caller drops (``filter_substantive_relations`` gate)
    UNRESOLVED   → technical failure or insufficient evidence

Failure Contract §1: the reviewer NEVER raises. Total LLM failure
demotes every HIGH-risk relation to UNRESOLVED — a technical failure
must never silently inflate apparent support.

Identity Contract §2: ``RelationReviewRecord.relation_id`` is always
the script-supplied id (``RelationAssertion.relation_id``, derived
from ``RelationKey.canonical().relation_id()``). The LLM cannot
influence identity; if the LLM fabricates a different ``relation_id``
in its output, the verdict is dropped (treated as if no verdict were
returned for that relation).

F8 discipline: ``relation_extractor`` / ``relation_models`` /
``relation_store`` / ``candidate_retrieval`` / ``claim_validator`` /
``claim_reviewer`` are untouched. The reviewer is an independently-
callable module (``review_high_risk_relations(assertions, ...)``);
Stage 6R caller wiring is deferred to a follow-up Task.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .claim import EvidenceRef
from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve
from .relation_models import RelationAssertion
from .relation_ontology import RelationPredicate, coerce


log = logging.getLogger(__name__)


PROMPT_KIND = "relation_reviewer"


# Spec §5.1: Bounded Evidence — the LLM is only charged for HIGH-risk
# predicate relations (low-risk relations default to SUPPORTED without
# consuming any quota). For HIGH-risk relations we batch at most 12
# per call to keep the prompt under budget. 12 (vs. Task 35's 8) is
# allowed because each relation carries evidence_excerpts bounded by
# ``MAX_EVIDENCE_EXCERPT_BYTES`` (300) — total payload stays small.
MAX_RELATIONS_PER_REVIEW_CALL = 12


# Spec §5.1: per-relation bounded evidence. Each cited EvidenceRef
# excerpt is capped at 300 bytes (Bounded Evidence Contract §3.2).
# Mirrors Task 35's ``TOPIC_ITEM_EXCERPT_BYTES`` for consistency.
MAX_EVIDENCE_EXCERPT_BYTES = 300


# Spec §5.1: predicates that imply causation or strict ordering and
# therefore need a second-opinion reviewer pass. The set is curated
# here (rather than read from ``RelationTypeSpec.high_risk``) because
# the relation ontology marks ``UNRESOLVED`` as high-risk too — we
# don't want the reviewer to charge for UNRESOLVED assertions (those
# are already demoted by the mechanical validator in Task 26).
#
# Spec also lists ``BROADER`` / ``NARROWER`` — these are NOT in the
# current ``RelationPredicate`` enum (Task 23's ontology). We coerce
# the string names through ``relation_ontology.coerce()`` so missing
# predicates collapse to ``UNRESOLVED`` rather than raising at module
# load — when Task 23 adds them, they automatically start counting as
# HIGH-risk without an edit here.
_HIGH_RISK_PREDICATE_NAMES: tuple[str, ...] = (
    "causes",
    "requires",
    "contradicts",
    "depends_on",
    "extends",
    "broader",
    "narrower",
)


def _build_high_risk_predicates() -> frozenset[RelationPredicate]:
    """Resolve ``_HIGH_RISK_PREDICATE_NAMES`` to enum members.

    Missing predicates (e.g. ``broader`` / ``narrower`` before the
    ontology adds them) collapse to ``UNRESOLVED`` and are *dropped*
    from the set — we only want real HIGH-risk members here.
    """
    out: set[RelationPredicate] = set()
    for name in _HIGH_RISK_PREDICATE_NAMES:
        member = coerce(name)
        if member is not RelationPredicate.UNRESOLVED:
            out.add(member)
    return frozenset(out)


_HIGH_RISK_PREDICATES: frozenset[RelationPredicate] = _build_high_risk_predicates()


def is_high_risk_predicate(predicate: RelationPredicate) -> bool:
    """Return True iff ``predicate`` is in the curated HIGH-risk set.

    HIGH-risk predicates are the ones whose semantic claims are easy
    to fabricate — causal / ordering / taxonomic assertions that the
    LLM might over-claim without strong evidence. LOW-risk predicates
    (``refines`` / ``supported_by`` / ``instance_of`` / symmetric
    predicates) are structural / encyclopedic — the LLM is unlikely to
    over-claim on them, so we don't charge the reviewer for them.

    Note: ``UNRESOLVED`` is *not* in this set — Task 26's mechanical
    validator already demotes UNRESOLVED assertions to the
    ``unresolved`` bucket; the reviewer is bypassed for them.
    """
    return predicate in _HIGH_RISK_PREDICATES


class RelationReviewStatus(str, Enum):
    """The four-value vocabulary the reviewer uses.

    Mirrors Task 35's ``TopicReviewerVerdict`` and Task 17's
    ``ReviewerVerdict`` (string-valued for JSON-friendly
    serialization).

    Mapping to caller decisions:
      SUPPORTED    → keep, proceed to ``RelationStore``
      OVERSTATED   → keep but down-weight (caller's choice)
      CONTRADICTED → drop (``filter_substantive_relations`` gate)
      UNRESOLVED   → reviewer could not decide (technical or evidence)
    """

    SUPPORTED = "supported"
    OVERSTATED = "overstated"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RelationReviewInput:
    """One relation to be reviewed by the LLM.

    Carries the script-owned ``relation_id`` (which the reviewer must
    round-trip verbatim — the LLM is NOT allowed to influence
    identity), the relation's structural triple (source / predicate /
    target), and the ``evidence_excerpts`` list of bounded evidence
    excerpts to compare against.

    The caller is responsible for slicing each excerpt to
    ``MAX_EVIDENCE_EXCERPT_BYTES`` (300). The reviewer also clamps
    these defensively — see :func:`_truncate_excerpts`.
    """

    relation_id: str
    source_page_id: str
    target_page_id: str
    predicate: RelationPredicate
    evidence_excerpts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RelationReviewRecord:
    """The reviewer's per-relation verdict.

    The caller decides what to do with the verdict — this record only
    reports the verdict, the reason, and the audit fields
    (``reviewer_fingerprint``, ``reviewed_at_ms``). Identity
    (``relation_id``) is the script-supplied id, never the LLM's.
    """

    relation_id: str
    source_page_id: str
    target_page_id: str
    predicate: RelationPredicate
    status: RelationReviewStatus
    reason: str
    confidence: float
    reviewer_fingerprint: str
    reviewed_at_ms: int


async def review_high_risk_relations(
    assertions: list[RelationAssertion],
    *,
    source_bytes: dict[str, bytes],
    llm: LLMClient,
    template: object | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[RelationReviewRecord]:
    """Re-check every HIGH-risk-predicate relation against its cited evidence.

    Behaviour:

      * LOW-risk predicates (i.e. ``is_high_risk_predicate(...) is False``)
        are returned as ``SUPPORTED`` without consuming any LLM quota.
      * HIGH-risk predicates are batched (≤
        ``MAX_RELATIONS_PER_REVIEW_CALL`` per call) and sent to the LLM.
        The verdict mapping is strict: SUPPORTED / OVERSTATED /
        CONTRADICTED surface verbatim; an unknown verdict string or a
        missing verdict for a given ``relation_id`` becomes UNRESOLVED.
      * If every retry of the LLM call raises, **no exception
        propagates** — every HIGH-risk relation is recorded as
        UNRESOLVED and the function returns. A technical failure never
        silently inflates apparent support (Failure Contract §1).
      * ``RelationReviewRecord.relation_id`` is always the
        caller-supplied id (Identity Contract §2). The LLM cannot
        influence identity; if the LLM fabricates a different id, the
        verdict is dropped (treated as if no verdict were returned for
        that relation).

    Returns one ``RelationReviewRecord`` per input, in the original
    order.

    Parameters
    ----------
    assertions:
        The ``RelationAssertion`` rows to review. The order is
        preserved in the returned records.
    source_bytes:
        ``source_page_id → raw source bytes`` map. Used to slice
        ``EvidenceRef`` excerpts (``source_bytes[ref.start_byte:ref.end_byte]``).
    llm:
        The LLM client (use ``FakeLLMClient`` in tests).
    template:
        Optional pre-resolved ``PromptTemplate``. When ``None`` the
        reviewer resolves the bundled prompt (``relation_reviewer.toml``)
        via :func:`resolve`.
    project_root:
        Optional project root for prompt override resolution
        (``.v7-prompts/relation_reviewer.toml``).
    max_retries:
        Maximum number of LLM attempts per batch before falling
        through to UNRESOLVED (default 3).
    """
    inputs = [_to_input(assertion, source_bytes) for assertion in assertions]

    # Resolve the prompt once (template=None → use bundled). If the
    # bundled TOML is missing (configuration failure), every HIGH-risk
    # input is demoted to UNRESOLVED rather than raising — same
    # fail-closed posture as a runtime LLM failure. LOW-risk inputs
    # keep their SUPPORTED bypass (no LLM needed for them).
    if template is None:
        try:
            template = _resolve_template(project_root)
        except RuntimeError as e:
            log.warning("relation_reviewer: prompt resolution failed: %s", e)
            return [
                _unresolved_record(
                    inp,
                    reason=f"reviewer config failure: {e}",
                )
                if is_high_risk_predicate(inp.predicate)
                else _supported_record(inp, template=None)
                for inp in inputs
            ]

    out: list[RelationReviewRecord | None] = [None] * len(inputs)
    high_indices: list[int] = [
        i for i, inp in enumerate(inputs)
        if is_high_risk_predicate(inp.predicate)
    ]

    # LOW-risk inputs first — they get SUPPORTED without LLM.
    for i, inp in enumerate(inputs):
        if i in high_indices:
            continue
        out[i] = _supported_record(inp, template)

    # HIGH-risk inputs: batch and call the LLM.
    for start in range(0, len(high_indices), MAX_RELATIONS_PER_REVIEW_CALL):
        batch_indices = high_indices[start:start + MAX_RELATIONS_PER_REVIEW_CALL]
        batch = [inputs[i] for i in batch_indices]

        relations_block, excerpts_template = _render_batch(batch)
        try:
            system_prompt, user_prompt = render_prompt(template, {
                "relations_block": relations_block,
                "max_relations": MAX_RELATIONS_PER_REVIEW_CALL,
                "evidence_excerpts_template": excerpts_template,
            })
        except Exception as e:
            # PromptSlotMissingError or similar — fail-closed.
            log.warning("relation_reviewer: prompt render failed: %s", e)
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

        # Build verdict index keyed by the *caller-supplied* relation_id.
        # The LLM's relation_id is matched only when it equals a known id.
        for i in batch_indices:
            inp = inputs[i]
            verdict_record = verdicts_by_id.get(inp.relation_id)
            if verdict_record is None:
                # No verdict returned — conservative: UNRESOLVED.
                out[i] = _unresolved_record(
                    inp,
                    reason="reviewer returned no verdict for this relation",
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

    # All slots are filled — narrow to list[RelationReviewRecord].
    final: list[RelationReviewRecord] = [r for r in out if r is not None]  # type: ignore[misc]
    assert len(final) == len(inputs), (
        "review_high_risk_relations must emit exactly one record per input"
    )
    return final


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_input(
    assertion: RelationAssertion,
    source_bytes: dict[str, bytes],
) -> RelationReviewInput:
    """Translate a ``RelationAssertion`` + ``source_bytes`` into a
    ``RelationReviewInput`` for the reviewer.

    The ``evidence_excerpts`` are sliced deterministically from the
    ``source_bytes[ref.start_byte:ref.end_byte]`` — never from LLM
    output (Bounded Evidence Contract §3.2). When the source page's
    bytes are missing from the map (a configuration error), the input
    is still valid but its excerpt list is empty (the reviewer marks
    it UNRESOLVED via "no evidence" — see render_batch).
    """
    raw_bytes = source_bytes.get(assertion.key.source_page_id, b"")
    excerpts: list[str] = []
    for ref in assertion.evidence_refs:
        if not isinstance(ref, EvidenceRef):
            continue
        end = min(ref.end_byte, ref.start_byte + MAX_EVIDENCE_EXCERPT_BYTES)
        end = max(end, ref.start_byte)  # defensive: empty range → ""
        if raw_bytes:
            excerpts.append(raw_bytes[ref.start_byte:end].decode(
                "utf-8", errors="replace",
            ))
    return RelationReviewInput(
        relation_id=assertion.relation_id,
        source_page_id=assertion.key.source_page_id,
        target_page_id=assertion.key.target_page_id,
        predicate=assertion.key.predicate,
        evidence_excerpts=excerpts,
    )


def _render_batch(
    batch: list[RelationReviewInput],
) -> tuple[str, str]:
    """Render the per-call ``relations_block`` +
    ``evidence_excerpts_template``.

    Each batch contributes one ``Relation N: id=…, source --[predicate]
    --> target`` line to ``relations_block`` (compact index the LLM can
    scan quickly), and a matching ``Evidence for Relation N: …`` block
    to the evidence appendix.

    Evidence is clipped per excerpt to ``MAX_EVIDENCE_EXCERPT_BYTES``
    (300) — defensive re-clip protects against a caller that forgot
    (Bounded Evidence Contract §3.2).
    """
    relations_lines: list[str] = []
    evidence_lines: list[str] = []
    for index, inp in enumerate(batch, start=1):
        relations_lines.append(
            f"Relation {index}: id={inp.relation_id}, "
            f"{inp.source_page_id} --[{inp.predicate.value}]--> "
            f"{inp.target_page_id}"
        )
        bounded = _truncate_excerpts(inp.evidence_excerpts)
        if bounded:
            quoted = "\n".join(f"  - {excerpt}" for excerpt in bounded)
        else:
            quoted = "  - (no evidence provided)"
        evidence_lines.append(f"Evidence for Relation {index}:\n{quoted}")

    return (
        "\n".join(relations_lines),
        "\n\n".join(evidence_lines),
    )


def _truncate_excerpts(excerpts: list[str]) -> list[str]:
    """Defensive Bounded Evidence clamp.

    Cap each excerpt at ``MAX_EVIDENCE_EXCERPT_BYTES`` (300) bytes —
    close enough for the byte budget; CJK chars are ~3 bytes each so
    300 chars ≈ 900 bytes worst case, which is still safely under the
    per-relation budget.
    """
    bounded: list[str] = []
    for raw in excerpts:
        excerpt = str(raw)
        bounded.append(excerpt[:MAX_EVIDENCE_EXCERPT_BYTES])
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
    failure (caller will mark every relation UNRESOLVED).

    A retry is triggered on any exception (including
    ``LLMResponseError``) so a malformed JSON response gets another
    chance. After ``max_retries`` failed attempts the function returns
    an empty dict — the caller marks every relation UNRESOLVED rather
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
                "relation_reviewer: response failed validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:  # any other LLM-side error
            last_error = e
            log.warning(
                "relation_reviewer: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
    log.info(
        "relation_reviewer: all %d attempts failed (last_error=%r)",
        max_retries, last_error,
    )
    return {}


def _payload_to_verdicts(
    payload: dict,
) -> dict[str, "_ParsedVerdict"]:
    """Translate the LLM JSON payload into ``{relation_id: _ParsedVerdict}``.

    Parsing rules (all script-owned — the LLM never decides whether its
    own verdict is valid):
      1. unknown ``verdict`` strings are dropped (the relation gets no
         verdict and is therefore UNRESOLVED — conservative default);
      2. malformed entries (not a dict, missing ``relation_id`` or
         ``verdict``) are dropped;
      3. duplicate ``relation_id``s: first wins (deterministic order
         is preserved by walking the list).
      4. ``confidence`` defaults to 1.0 if missing or non-numeric —
         the verdict itself is the source of truth; confidence is
         metadata for operator triage.
    """
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        return {}

    out: dict[str, _ParsedVerdict] = {}
    for entry in raw_verdicts:
        if not isinstance(entry, dict):
            continue
        relation_id = entry.get("relation_id")
        verdict_raw = entry.get("verdict")
        if not isinstance(relation_id, str) or not isinstance(verdict_raw, str):
            continue
        if relation_id in out:
            continue  # duplicate: first wins
        try:
            verdict = RelationReviewStatus(verdict_raw)
        except ValueError:
            # Unknown verdict string — drop it; caller demotes to UNRESOLVED.
            continue
        try:
            confidence = float(entry.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        out[relation_id] = _ParsedVerdict(verdict=verdict, confidence=confidence)
    return out


@dataclass(frozen=True)
class _ParsedVerdict:
    """Internal — verdict + the LLM's confidence metadata."""

    verdict: RelationReviewStatus
    confidence: float


def _supported_record(
    inp: RelationReviewInput,
    template: object,
) -> RelationReviewRecord:
    """Build a SUPPORTED record for a LOW-risk predicate (no LLM call)."""
    return RelationReviewRecord(
        relation_id=inp.relation_id,
        source_page_id=inp.source_page_id,
        target_page_id=inp.target_page_id,
        predicate=inp.predicate,
        status=RelationReviewStatus.SUPPORTED,
        reason="low-risk predicate; bypassed reviewer (Bounded Evidence)",
        confidence=1.0,
        reviewer_fingerprint=_fingerprint(template, inputs=[inp]),
        reviewed_at_ms=_now_ms(),
    )


def _unresolved_record(
    inp: RelationReviewInput,
    *,
    reason: str,
) -> RelationReviewRecord:
    """Build an UNRESOLVED record (technical failure / no verdict)."""
    return RelationReviewRecord(
        relation_id=inp.relation_id,
        source_page_id=inp.source_page_id,
        target_page_id=inp.target_page_id,
        predicate=inp.predicate,
        status=RelationReviewStatus.UNRESOLVED,
        reason=reason[:200],  # spec §2 reason <=200 chars
        confidence=0.0,
        reviewer_fingerprint=_fingerprint(None, inputs=[inp]),
        reviewed_at_ms=_now_ms(),
    )


def _verdict_to_record(
    inp: RelationReviewInput,
    *,
    verdict_record: "_ParsedVerdict",
    template: object,
) -> RelationReviewRecord:
    """Convert one LLM verdict + the caller's input into a record."""
    reason = _reason_for_verdict(verdict_record.verdict)
    return RelationReviewRecord(
        relation_id=inp.relation_id,
        source_page_id=inp.source_page_id,
        target_page_id=inp.target_page_id,
        predicate=inp.predicate,
        status=verdict_record.verdict,
        reason=reason[:200],
        confidence=verdict_record.confidence,
        reviewer_fingerprint=_fingerprint(template, inputs=[inp]),
        reviewed_at_ms=_now_ms(),
    )


def _reason_for_verdict(verdict: RelationReviewStatus) -> str:
    return {
        RelationReviewStatus.SUPPORTED: "reviewer: relation matches evidence",
        RelationReviewStatus.OVERSTATED: "reviewer: relation wider than evidence",
        RelationReviewStatus.CONTRADICTED: "reviewer: evidence contradicts relation",
        RelationReviewStatus.UNRESOLVED: "reviewer: unresolved",
    }[verdict]


def _fingerprint(
    template: object | None,
    *,
    inputs: list[RelationReviewInput],
) -> str:
    """Stable audit hash for a reviewer call.

    Combines the resolved prompt's identity (kind + version + a short
    body sample) with the inputs' predicates + relation_ids. A change
    in either side moves the fingerprint — operators can compare across
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
        f"{inp.relation_id}::{inp.predicate.value}" for inp in inputs
    )
    identity = f"rrev|{template_part}|{inputs_part}"
    return "rrev-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


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
    "MAX_RELATIONS_PER_REVIEW_CALL",
    "MAX_EVIDENCE_EXCERPT_BYTES",
    "PROMPT_KIND",
    "RelationReviewStatus",
    "RelationReviewInput",
    "RelationReviewRecord",
    "is_high_risk_predicate",
    "review_high_risk_relations",
]
