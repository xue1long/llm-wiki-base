"""Stage 5B deterministic page synthesis + FillResult (Task 18).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md``
Task 18 (Stage 5 — Stage 5B deterministic page synthesis + FillResult).

This module is the *deterministic* glue between Stage 5A
(``claim_extractor.extract_slot_claims``), Task 16
(``claim_validator.validate_claim`` + ``filter_substantive_claims``) and
Task 17 (``claim_reviewer.review_high_risk_claims``). After Stage 5B
returns, every ``Claim`` either survives as a SUPPORTED bullet in a slot,
is demoted to ``INSUFFICIENT_EVIDENCE`` and dropped from rendering, or has
been declared ``CONFLICTING`` — at which point the whole page is marked
``FillStatus.CONFLICTING`` regardless of how many other claims survived.

Why this stage is deterministic
------------------------------
Stage 5B never asks the LLM another question. It does string formatting,
token overlap, and a fixed ``FillStatus`` ↔ ``ExtractionStatus`` map.
That keeps the failure surface tight: a Technical failure can ONLY come
from the underlying LLM calls (Stage 5A / Task 17 reviewer), and the
mapping ``FillStatus.TECHNICAL_FAILURE → ExtractionStatus.FAILED`` is the
hard contract from Failure Contract §1.3 — a technical failure NEVER
silently becomes a written page.

Coherence check
---------------
A lightweight syntactic check: definition slot claims that carry negation
("不是/并非/不能/无法/不应") AND a token overlap with characteristics slot
claims (same first-token) trigger ``FillStatus.COHERENCE_FAILED``. No LLM
call. The point is to catch the obvious "X 不是 Y" + "Y 的特征是 …"
contradiction before publication, without paying for another reviewer
budget on Stage 5B.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .canonical_spans import CanonicalSpan
from .claim import Claim, ClaimSupport
from .claim_extractor import extract_slot_claims
from .claim_reviewer import review_high_risk_claims
from .claim_validator import filter_substantive_claims, validate_claim
from .failures import ExtractionStatus
from .llm_client import LLMClient
from .segmentation import CanonicalItem

if TYPE_CHECKING:
    from .slot_filler import CONCEPT_SLOTS, ConceptPage
    from .topic_clusterer import Topic


log = logging.getLogger(__name__)


# Local mirror of ``CONCEPT_SLOTS`` from ``slot_filler`` — duplicated here
# rather than imported at module level to break the
# ``slot_filler`` ⟷ ``page_synthesizer`` import cycle. The two MUST stay
# in lock-step (both are 5-tuple literals).
_CONCEPT_SLOTS: tuple[str, ...] = (
    "definition",
    "characteristics",
    "examples",
    "related_concepts",
    "references",
)


# Topic-completion threshold below which a PARTIAL/CONFLICTING page is
# bumped down to BLOCKED (must go to review before publishing).
_PARTIAL_COMPLETION_THRESHOLD = 0.4


# Negation markers that, when combined with a definition ↔ characteristics
# first-token overlap, raise ``COHERENCE_FAILED``. Deliberately narrow:
# these are the phrases Task 15's risk classifier already flagged as HIGH
# (see ``_RISK_PATTERNS`` in claim_extractor.py), so we reuse the
# vocabulary the rest of the pipeline already speaks.
_COHERENCE_NEGATION_RE = re.compile(r"不是|并非|不能|无法|不应|不需要|不同于")


# ---------------------------------------------------------------------------
# Public dataclasses / enums
# ---------------------------------------------------------------------------


class FillStatus(str, Enum):
    """Per-page Stage 5B outcome.

    Mapped to ``ExtractionStatus`` (5-state) by ``map_fill_to_extraction``.
    The legacy 3-state ``OK``/``NEEDS_REVIEW``/``INCOMPLETE`` are not
    re-emitted here — Stage 7 wiki_writer is the layer that re-derives a
    legacy view if it needs one.
    """

    FILLED = "filled"                      # all 5 slots have supported+evidence
    PARTIAL = "partial"                    # some slots have content, others empty
    INSUFFICIENT = "insufficient"          # every slot is empty (mechanical + reviewer demotion)
    CONFLICTING = "conflicting"            # at least one claim CONFLICTING
    COHERENCE_FAILED = "coherence_failed"  # definition ↔ characteristics contradict
    TECHNICAL_FAILURE = "technical_failure"  # LLM up/down-stream raised


@dataclass
class FillResult:
    """Stage 5B output: one topic → one ``FillResult`` (never raises).

    ``legacy_page`` is filled when ``fill_slots_v2`` bridges to the
    Stage-7 ``ConceptPage`` shape (``wiki_writer.py`` depends on it).
    """

    topic_id: str
    title: str
    status: FillStatus
    slots: dict[str, str]                                    # {slot_name: rendered markdown}
    needs_review_slots: tuple[str, ...]                      # which slots are empty
    metrics: dict[str, Any]                                  # topic_completion_ratio, claim_support_ratio, reviewer_verdicts_count
    generator_fingerprint: str                               # sha1 of the slot filler template
    warnings: list[str] = field(default_factory=list)
    technical_error: str | None = None                       # set only when status==TECHNICAL_FAILURE
    legacy_page: ConceptPage | None = None                   # bridge for Stage 7 wiki_writer
    claim_audit: list[dict[str, Any]] = field(default_factory=list)  # per-claim verdict history


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def synthesize_slot(slot_name: str, claims: list[Claim]) -> str:
    """Render Markdown for one slot from its SUPPORTED claims.

    Pure: only claims with ``ClaimSupport.SUPPORTED`` AND non-empty
    ``evidence_refs`` are rendered (i.e. ``filter_substantive_claims`` is
    the gate). Output is a deterministic bullet list in input order. Empty
    input → empty body so the caller marks the slot as needs_review.

    Sentence-final punctuation: each claim's text is rendered verbatim,
    with a trailing "。" appended unless the text already ends with "。"
    (so we don't double-punctuate).
    """
    rendered: list[str] = []
    for claim in filter_substantive_claims(claims):
        text = claim.text.strip()
        if not text:
            continue
        if not text.endswith("。"):
            text = f"{text}。"
        rendered.append(f"- {text}")
    return "\n".join(rendered)


def map_fill_to_extraction(fill: FillResult) -> ExtractionStatus:
    """Map ``FillStatus`` → ``ExtractionStatus`` (5-state).

    Hard contract: ``TECHNICAL_FAILURE → FAILED`` (never ``WRITTEN``).
    ``INSUFFICIENT`` / ``COHERENCE_FAILED`` → ``BLOCKED`` (review needed).
    ``FILLED`` → ``WRITTEN`` unconditionally. ``PARTIAL`` and ``CONFLICTING``
    are gated by ``metrics.topic_completion_ratio``:
        >= 0.4  → ``WRITTEN`` (partial page is still worth publishing)
        <  0.4  → ``BLOCKED`` (too sparse — must go to review first).
    """
    status = fill.status
    completion = float(fill.metrics.get("topic_completion_ratio", 0.0) or 0.0)

    if status is FillStatus.TECHNICAL_FAILURE:
        return ExtractionStatus.FAILED
    if status is FillStatus.INSUFFICIENT:
        return ExtractionStatus.BLOCKED
    if status is FillStatus.COHERENCE_FAILED:
        return ExtractionStatus.BLOCKED
    if status is FillStatus.FILLED:
        return ExtractionStatus.WRITTEN
    if status in {FillStatus.PARTIAL, FillStatus.CONFLICTING}:
        return (
            ExtractionStatus.WRITTEN
            if completion >= _PARTIAL_COMPLETION_THRESHOLD
            else ExtractionStatus.BLOCKED
        )
    # Default for any unrecognised status: BLOCKED (safest).
    return ExtractionStatus.BLOCKED


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _slot_claims(claims: list[Claim], slot_name: str) -> list[Claim]:
    """All claims for one slot, input order preserved."""
    return [c for c in claims if c.slot_name == slot_name]


def _slot_filled(slot_body: str) -> bool:
    """A slot counts as filled iff its rendered body is non-empty."""
    return bool(slot_body.strip())


def _first_token(text: str) -> str:
    """First non-punctuation CJK / ASCII token used by the coherence check.

    Strips leading punctuation and quotes so "X 不是 Y" and "X，并非 Y"
    yield the same token. Returns "" for empty / pure-punctuation input.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    # Drop common CJK punctuation / quotes so the first real character is
    # what we compare on.
    for ch in "「『《〈（【\"'":
        if stripped.startswith(ch):
            stripped = stripped[1:]
    stripped = stripped.strip()
    if not stripped:
        return ""
    # First run of CJK characters, ASCII letters / digits, or single punctuation.
    match = re.match(r"[\u4e00-\u9fffA-Za-z0-9_]+", stripped)
    return match.group(0) if match else ""


def _coherence_check(claims: list[Claim]) -> bool:
    """Return True iff definition ↔ characteristics look contradictory.

    Triggers when BOTH hold:
      * definition slot has a claim whose text matches the negation
        vocabulary ("不是/并非/不能/无法/不应");
      * characteristics slot has a claim whose first token equals the
        definition claim's first token (same subject word).

    Lightweight by design — no LLM. The point is to flag the obvious
    self-contradiction before publication; subtle semantic conflicts
    remain Task 17 reviewer's job (and were handled upstream).
    """
    def_claims = [c for c in claims if c.slot_name == "definition"]
    char_claims = [c for c in claims if c.slot_name == "characteristics"]
    if not def_claims or not char_claims:
        return False

    char_tokens = {_first_token(c.text) for c in char_claims}
    char_tokens.discard("")
    if not char_tokens:
        return False

    for def_claim in def_claims:
        if not _COHERENCE_NEGATION_RE.search(def_claim.text):
            continue
        def_token = _first_token(def_claim.text)
        if def_token and def_token in char_tokens:
            return True
    return False


def _generator_fingerprint() -> str:
    """Script-owned short fingerprint of the Stage 5 prompt templates.

    sha1 of ``fill_slots_extract.toml + claim_reviewer.toml`` bytes
    truncated to 12 hex — changes whenever the prompt authoring changes,
    so downstream caches / re-runs are deterministic.
    """
    parts: list[bytes] = []
    here = Path(__file__).resolve().parent
    for name in ("fill_slots_extract.toml", "claim_reviewer.toml"):
        path = here / "prompts" / "builtin" / name
        try:
            parts.append(path.read_bytes())
        except OSError:
            # Missing prompt should not crash the page synthesizer — fall
            # back to the filename as a stable placeholder so the
            # fingerprint is still deterministic for this build.
            parts.append(name.encode("utf-8"))
    digest = hashlib.sha1(b"\n".join(parts)).hexdigest()[:12]
    return digest


def _compute_metrics(
    *,
    slots: dict[str, str],
    claims: list[Claim],
) -> dict[str, Any]:
    """Per-page metric block used by ``map_fill_to_extraction`` + audit."""
    filled_count = sum(1 for body in slots.values() if _slot_filled(body))
    total_slots = max(1, len(_CONCEPT_SLOTS))
    completion = filled_count / total_slots

    supported = sum(1 for c in claims if c.support is ClaimSupport.SUPPORTED)
    total_claims = max(1, len(claims))
    support_ratio = supported / total_claims

    reviewer_count = sum(1 for c in claims if c.risk.value == "high")

    return {
        "topic_completion_ratio": completion,
        "claim_support_ratio": support_ratio,
        "reviewer_verdicts_count": reviewer_count,
    }


def _audit_claim(claim: Claim, *, topic_items: list[CanonicalItem], topic_id: str) -> dict[str, Any]:
    """Per-claim audit record (debug). Records validator report + post-reviewer support."""
    report = validate_claim(claim, topic_items=topic_items, topic_id=topic_id)
    return {
        "claim_id": claim.claim_id,
        "slot_name": claim.slot_name,
        "support": claim.support.value,
        "risk": claim.risk.value,
        "is_valid": report.is_valid,
        "violations": list(report.violations),
        "needs_reviewer": report.needs_reviewer,
    }


# ---------------------------------------------------------------------------
# Main entry: fill_slots_v2
# ---------------------------------------------------------------------------


async def fill_slots_v2(
    topic: Any,
    *,
    spans_per_slot: Mapping[str, list[CanonicalSpan]],
    topic_items: list[CanonicalItem],
    source_bytes: bytes,
    llm: LLMClient,
    project_root: Path | str | None = None,
    topic_label: str | None = None,
    max_retries: int = 3,
) -> FillResult:
    """Stage 5B main entry: per-slot Stage 5A → reviewer → validator → synthesize.

    Returns a ``FillResult``. NEVER raises (Failure Contract §1.3): a Stage
    5A ``RuntimeError`` (every retry failed) → ``FillStatus.TECHNICAL_FAILURE``
    with ``technical_error=str(e)``. Reviewer-level failures are already
    fail-closed (Task 17) — they demote HIGH-risk claims, they do not raise.

    Output status precedence (first match wins):

      1. any Stage 5A ``RuntimeError`` → ``TECHNICAL_FAILURE``
      2. coherence check fired          → ``COHERENCE_FAILED``
      3. every slot empty               → ``INSUFFICIENT``
      4. any claim ``CONFLICTING``      → ``CONFLICTING``
      5. every slot has content         → ``FILLED``
      6. otherwise                      → ``PARTIAL``

    ``topic_label`` defaults to ``topic.title`` so the LLM has a readable
    context label. ``topic_items`` is the canonical item list (Stage 2
    output) used by ``validate_claim``; ``spans_per_slot`` maps each of
    the 5 ``CONCEPT_SLOTS`` to its candidate span list (Stage 5A input).
    """
    topic_id, title, sources = _topic_parts(topic)
    label = topic_label or title or topic_id

    warnings: list[str] = []
    technical_error: str | None = None
    technical_failed = False

    # Stage 5A: one SlotExtraction per slot.
    per_slot_claims: dict[str, list[Claim]] = {}
    for slot_name in _CONCEPT_SLOTS:
        slot_spans = list(spans_per_slot.get(slot_name, []))
        try:
            extraction = await extract_slot_claims(
                slot_name,
                topic_label=label,
                spans=slot_spans,
                llm=llm,
                project_root=project_root,
                source_bytes=source_bytes,
                max_retries=max_retries,
            )
        except RuntimeError as e:
            # Technical failure on this slot — record it and keep going so
            # the final FillResult is still a value object (not an
            # exception). Other slots may still succeed, and the
            # TECHNICAL_FAILURE status is decided after the loop.
            warnings.append(f"extract_slot_claims[{slot_name}] failed: {e}")
            technical_error = str(e)
            technical_failed = True
            per_slot_claims[slot_name] = []
            continue

        per_slot_claims[slot_name] = list(extraction.claims)

    # Flatten + reviewer (Task 17). Reviewer is fail-closed: it demotes
    # HIGH-risk claims on LLM error rather than raising.
    flat_claims: list[Claim] = []
    for slot_name in _CONCEPT_SLOTS:
        flat_claims.extend(per_slot_claims.get(slot_name, []))
    if flat_claims:
        flat_claims = await review_high_risk_claims(
            flat_claims,
            source_bytes=source_bytes,
            llm=llm,
            project_root=project_root,
            max_retries=max_retries,
        )

    # Audit each claim (post-reviewer).
    claim_audit = [
        _audit_claim(c, topic_items=topic_items, topic_id=topic_id)
        for c in flat_claims
    ]

    # Render slots.
    slots: dict[str, str] = {
        slot_name: synthesize_slot(slot_name, _slot_claims(flat_claims, slot_name))
        for slot_name in _CONCEPT_SLOTS
    }
    needs_review_slots = tuple(
        name for name, body in slots.items() if not _slot_filled(body)
    )

    metrics = _compute_metrics(slots=slots, claims=flat_claims)
    metrics["coherence_conflict"] = _coherence_check(flat_claims)

    # Status precedence — see docstring.
    if technical_failed:
        status = FillStatus.TECHNICAL_FAILURE
    elif metrics["coherence_conflict"]:
        status = FillStatus.COHERENCE_FAILED
    elif not flat_claims or all(
        c.support is ClaimSupport.INSUFFICIENT_EVIDENCE for c in flat_claims
    ):
        status = FillStatus.INSUFFICIENT
    elif any(c.support is ClaimSupport.CONFLICTING for c in flat_claims):
        status = FillStatus.CONFLICTING
    elif all(_slot_filled(slots[name]) for name in _CONCEPT_SLOTS):
        status = FillStatus.FILLED
    else:
        status = FillStatus.PARTIAL

    # Bridge to legacy ``ConceptPage`` so Stage 7 wiki_writer doesn't break
    # until Task 19-22 lands. Best-effort: a legacy failure must NOT mask
    # the v2 outcome, so we swallow any error and leave ``legacy_page``
    # as ``None`` with a warning.
    legacy_page: ConceptPage | None = None
    try:
        legacy_page = await _bridge_legacy_page(
            topic=topic,
            topic_id=topic_id,
            title=title,
            sources=sources,
            llm=llm,
            source_bytes=source_bytes,
            project_root=project_root,
            max_retries=max_retries,
        )
    except Exception as e:  # pragma: no cover — defensive: legacy is best-effort
        warnings.append(f"legacy fill_slots bridge failed: {e}")

    return FillResult(
        topic_id=topic_id,
        title=title,
        status=status,
        slots=slots,
        needs_review_slots=needs_review_slots,
        metrics=metrics,
        generator_fingerprint=_generator_fingerprint(),
        warnings=warnings,
        technical_error=technical_error,
        legacy_page=legacy_page,
        claim_audit=claim_audit,
    )


async def _bridge_legacy_page(
    *,
    topic: Any,
    topic_id: str,
    title: str,
    sources: list[str],
    llm: LLMClient,
    source_bytes: bytes,
    project_root: Path | str | None,
    max_retries: int,
) -> "ConceptPage | None":
    """Best-effort bridge to ``fill_slots`` for backwards compatibility.

    Stage 7 wiki_writer currently consumes ``ConceptPage``; we keep that
    contract working by reusing the legacy LLM call. Failures here are
    *not* technical failures of Stage 5B — the v2 result already carries
    every signal Stage 7 needs in ``slots`` / ``needs_review_slots`` /
    ``metrics``. We only log a warning and return ``None``.

    The ``fill_slots`` symbol is imported lazily to break the
    ``slot_filler`` ⟷ ``page_synthesizer`` import cycle.
    """
    from .slot_filler import fill_slots
    source_text = source_bytes.decode("utf-8", errors="replace")
    item_texts: dict[str, str] = {}
    # Best-effort item_texts — Stage 7's wiki_writer only checks
    # has_evidence, which depends on item_index validity; passing
    # ``item_ids`` (source ids) as the keys is safe.
    if hasattr(topic, "items") and getattr(topic, "items", None):
        for it in getattr(topic, "items", []):
            item_texts[getattr(it, "item_id", "")] = getattr(it, "text", "")
    else:
        for s in sources:
            item_texts[str(s)] = source_text

    return await fill_slots(
        topic=topic,
        source_text=source_text,
        llm=llm,
        item_texts=item_texts or None,
        project_root=project_root,
        max_retries=max_retries,
    )


def _topic_parts(topic: Any) -> tuple[str, str, list[str]]:
    """Normalise ``topic`` (Topic dataclass / dict / object)."""
    if hasattr(topic, "id") and hasattr(topic, "title"):
        sources = list(getattr(topic, "item_ids", []) or [])
        return str(topic.id), str(topic.title), sources
    if isinstance(topic, Mapping):
        return (
            str(topic.get("id", "")),
            str(topic.get("title", "")),
            [str(s) for s in topic.get("item_ids", []) or []],
        )
    sources = list(getattr(topic, "item_ids", []) or [])
    return (
        str(getattr(topic, "id", "")),
        str(getattr(topic, "title", "")),
        sources,
    )


__all__ = [
    "FillResult",
    "FillStatus",
    "fill_slots_v2",
    "map_fill_to_extraction",
    "synthesize_slot",
]
