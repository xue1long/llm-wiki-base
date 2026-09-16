"""Canonical claim projection — render canonical view from member claims (Task 44).

Pure projection layer: takes a ``CanonicalClaim`` (Phase 2 output) plus
its member ``Claim`` objects, returns a ``CanonicalClaimView`` suitable for
wiki rendering. No LLM, no IO.

Decision → view mapping:
  * SAME:    text = highest-confidence member text + member_summary
  * OVERLAP: text = all member texts joined by "\\n"
  * CONFLICT: text = all member texts joined by "\\n---\\n" (markdown rule)
  * SINGLE:  text = single member text directly

Evidence refs are always dedup'd by (item_id, start_byte, end_byte).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.pipeline.v7_extract.claim import Claim, EvidenceRef
from src.reconciliation.canonical_claim_models import CanonicalClaim


class CanonicalViewKind(str, Enum):
    """Same value names as ClaimReconciliationDecision but used here for the
    view-layer kind — kept independent so the projection layer can evolve
    without changing the reconciliation vocabulary."""

    SAME = "same"
    OVERLAP = "overlap"
    CONFLICT = "conflict"
    SINGLE = "single"


@dataclass
class CanonicalClaimView:
    canonical_claim_id: str
    view_kind: CanonicalViewKind
    text: str
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    member_summary: str = ""


def _dedup_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, int, int]] = set()
    out: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.item_id, ref.start_byte, ref.end_byte)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def project_canonical_view(
    canonical_claim: CanonicalClaim,
    member_claims: list[Claim],
) -> CanonicalClaimView:
    """Build a renderable view from ``canonical_claim`` + its member claims.

    ``member_claims`` is the list of all ``Claim`` objects referenced by
    ``canonical_claim.member_claim_ids``. The order of the resulting
    ``text`` is deterministic (member_claim_ids order).
    """
    by_id: dict[str, Claim] = {c.claim_id: c for c in member_claims}
    ordered: list[Claim] = []
    for cid in canonical_claim.member_claim_ids:
        c = by_id.get(cid)
        if c is not None:
            ordered.append(c)

    decision = canonical_claim.decision.value
    n = len(ordered)

    if n == 0:
        text = canonical_claim.text
        member_summary = "0 members"
        confidence = canonical_claim.confidence
    elif n == 1 or decision == "single":
        text = ordered[0].text
        member_summary = f"1 member: claim_id={ordered[0].claim_id}"
        confidence = ordered[0].confidence
    elif decision == "same":
        # Pick the highest-confidence member as canonical text; member_summary
        # lists all members' truncated texts for context.
        best = max(ordered, key=lambda c: c.confidence)
        text = best.text
        snippets = [c.text[:60] for c in ordered]
        member_summary = f"{n} members (SAME): " + " | ".join(snippets)
        if len(member_summary) > 200:
            member_summary = member_summary[:200] + "..."
        confidence = sum(c.confidence for c in ordered) / n
    elif decision == "overlap":
        text = "\n".join(c.text for c in ordered)
        member_summary = f"{n} members (OVERLAP)"
        confidence = sum(c.confidence for c in ordered) / n
    elif decision == "conflict":
        text = "\n---\n".join(c.text for c in ordered)
        member_summary = f"{n} members (CONFLICT)"
        confidence = sum(c.confidence for c in ordered) / n
    else:
        # Unknown / unresolved — fall through to single text (best effort).
        text = canonical_claim.text or (ordered[0].text if ordered else "")
        member_summary = f"{n} members (decision={decision})"
        confidence = canonical_claim.confidence

    # Aggregate evidence from all members + dedup.
    all_refs: list[EvidenceRef] = []
    for c in ordered:
        all_refs.extend(c.evidence_refs)
    deduped = _dedup_evidence_refs(all_refs)

    try:
        view_kind = CanonicalViewKind(decision)
    except ValueError:
        view_kind = CanonicalViewKind.SINGLE

    return CanonicalClaimView(
        canonical_claim_id=canonical_claim.canonical_claim_id,
        view_kind=view_kind,
        text=text,
        evidence_refs=deduped,
        confidence=confidence,
        member_summary=member_summary,
    )


__all__ = [
    "CanonicalClaimView",
    "CanonicalViewKind",
    "project_canonical_view",
]