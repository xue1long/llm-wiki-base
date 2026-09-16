"""Stage 5 claim validator — script-owned mechanical validation (Task 16).

Plan: ``docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md``
Task 16 (Stage 5 — Claim validator, 10 mechanical invariants).

Design rule: **the LLM never decides whether its own evidence is valid.**
Stage 5A (``claim_extractor``) already refuses to let the LLM emit byte
offsets — it maps LLM-cited span ids back to ``CanonicalSpan`` byte ranges.
This module is the second half of that contract: it re-checks the resulting
``Claim`` against the canonical items of the topic it belongs to, and the
verdict is a pure function of data (no model call, no heuristic, no
"confidence" threshold). Ten invariants decide; the script decides.

The ten invariants (each emits a stable violation code — the prefix before
the first ``:`` is the machine-readable part, the suffix is detail):

  ===== ==================================== ===========================
  Code  Rule                                 Why it exists
  ===== ==================================== ===========================
  I1    substantive claim has >= 1 ref       a claim with no evidence is
                                             an assertion, not knowledge
  I2    item.start <= start < end <=        a ref must describe text of
        item.end                             the item it names
  I3    ref.item_id in topic item ids        evidence must come from this
                                             topic's own items
  I4    ref.item_id has no ``__other__``     the residual bucket is never
                                             a citable source
  I5    no duplicate (item_id, start, end)   duplicated evidence inflates
                                             apparent support
  I6    end > start                          an empty span proves nothing
  I7    length >= MIN_EVIDENCE_BYTES (30)    Bounded Evidence Contract §3.2
  I8    length <= MAX_EVIDENCE_BYTES (3000)  Bounded Evidence Contract §3.2
  I9    start >= 0                           negative offsets are
                                             impossible-but-checked
  I10   SUPPORTED cannot have zero refs      defence in depth for I1: the
                                             Claim model carries no
                                             technical-failure status
                                             (Failure Contract §1.3), so
                                             "supported without evidence"
                                             has nowhere to hide
  ===== ==================================== ===========================
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .claim import Claim, ClaimRisk, ClaimSupport, EvidenceRef
from .segmentation import CanonicalItem
from .topic_clusterer import OTHER_TOPIC_ID

# Bounded Evidence Contract §3.2: an evidence span must be long enough to be
# re-readable on its own and short enough to stay a *bounded* pointer.
MIN_EVIDENCE_BYTES = 30
MAX_EVIDENCE_BYTES = 3000


@dataclass
class ClaimValidationReport:
    """Outcome of the ten mechanical invariants for one claim.

    ``violations`` holds ``f"{code}:{detail}"`` strings (detail is omitted
    where it would be noise); ``is_valid`` is simply "no violations".

    ``needs_reviewer`` is deliberately NOT ``is_valid`` and NOT "any
    violation": the semantic reviewer (Task 17) is expensive, so it is only
    worth invoking for claims that are simultaneously high-risk,
    claimed-supported, and actually carrying evidence. Everything else is
    already handled mechanically — an invalid claim is dropped, and a
    low-risk or unsupported claim has nothing for a reviewer to add.
    """

    claim_id: str
    is_valid: bool
    violations: list[str] = field(default_factory=list)
    needs_reviewer: bool = False


def validate_claim(
    claim: Claim,
    *,
    topic_items: list[CanonicalItem],
    topic_id: str,
) -> ClaimValidationReport:
    """Run all ten invariants over *claim* and report the violations.

    *topic_items* is the full item list of the topic the claim was extracted
    for; *topic_id* names that topic (used in diagnostics). Every ref is
    checked independently — one bad ref never hides another — and the
    returned order is stable (I1/I10 first, then ref-scoped codes in ref
    order), so callers can log the report verbatim.
    """
    violations: list[str] = []
    refs = claim.evidence_refs

    # -- claim-scoped invariants -------------------------------------------
    if claim.is_substantive() and not refs:
        violations.append(f"I1_no_evidence:{claim.claim_id}")
    if claim.support is ClaimSupport.SUPPORTED and not refs:
        violations.append(
            f"I10_technical_failure_cannot_be_supported:{claim.claim_id}"
        )

    # -- ref-scoped invariants ---------------------------------------------
    items_by_id = {item.item_id: item for item in topic_items}
    seen: set[tuple[str, int, int]] = set()

    for ref in refs:
        identity = (ref.item_id, ref.start_byte, ref.end_byte)
        if identity in seen:
            violations.append(f"I5_duplicate_ref:{_ref_label(ref)}")
        else:
            seen.add(identity)

        if ref.start_byte < 0:
            violations.append(f"I9_ref_out_of_bounds:{ref.start_byte}")

        if ref.end_byte <= ref.start_byte:
            violations.append(f"I6_empty_span:{_ref_label(ref)}")

        length = ref.end_byte - ref.start_byte
        if length < MIN_EVIDENCE_BYTES:
            violations.append(f"I7_span_too_short:{length}")
        if length > MAX_EVIDENCE_BYTES:
            violations.append(f"I8_span_too_long:{length}")

        if OTHER_TOPIC_ID in ref.item_id:
            violations.append(f"I4_other_topic_ref:{ref.item_id}")

        item = items_by_id.get(ref.item_id)
        if item is None:
            violations.append(f"I3_cross_topic:{ref.item_id} (topic {topic_id})")
            continue  # no item -> bounds (I2) cannot be evaluated

        if not (
            item.start_byte <= ref.start_byte
            and ref.start_byte < ref.end_byte
            and ref.end_byte <= item.end_byte
        ):
            violations.append(
                f"I2_span_outside_item:{_ref_label(ref)} "
                f"item=[{item.start_byte},{item.end_byte})"
            )

    return ClaimValidationReport(
        claim_id=claim.claim_id,
        is_valid=not violations,
        violations=violations,
        needs_reviewer=(
            claim.risk is ClaimRisk.HIGH
            and claim.support is ClaimSupport.SUPPORTED
            and bool(refs)
        ),
    )


def filter_substantive_claims(claims: list[Claim]) -> list[Claim]:
    """Keep only claims that may reach a rendered page.

    The gate is ``support == SUPPORTED`` **and** at least one evidence ref —
    the I5-enforcement gate for rendering: an unsupported claim 不得进入
    rendered page ("no unsupported claim enters a rendered page"). This is
    the last mechanical filter before Stage 6/7 rendering, so a claim whose
    support was demoted (by this module or by Task 17's reviewer) can never
    be published, and order is preserved for deterministic output.
    """
    return [
        claim
        for claim in claims
        if claim.support is ClaimSupport.SUPPORTED and bool(claim.evidence_refs)
    ]


def _ref_label(ref: EvidenceRef) -> str:
    """Short stable ref label for diagnostics: ``item_id:start-end``."""
    return f"{ref.item_id}:{ref.start_byte}-{ref.end_byte}"


__all__ = [
    "MAX_EVIDENCE_BYTES",
    "MIN_EVIDENCE_BYTES",
    "ClaimValidationReport",
    "filter_substantive_claims",
    "validate_claim",
]
