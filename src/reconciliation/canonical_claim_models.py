"""Task 34 — CanonicalClaim model + ClaimReconciliationDecision enum.

Phase 2 of the reconciliation plane (ADR 0012). After Phase 1 groups
wiki pages into canonical concepts (:py:class:`CanonicalConcept`),
Phase 2 groups member claims (extracted by Stage 5B) within each
canonical into :py:class:`CanonicalClaim` aggregates.

Vocabulary
----------
  * ``ClaimReconciliationDecision`` — the 5-way verdict an LLM resolver
    can emit per claim-pair (a subset of the 8-way
    :py:class:`ReconciliationDecision` used by Phase 1).
  * ``CanonicalClaim`` — the aggregate that owns a set of equivalent
    member claims.
  * ``ClaimDecisionRecord`` — a single verdict emitted by the LLM
    resolver, scoped to a claim-pair (pair_id).
  * :py:func:`canonical_claim_id_for` — script-owned id helper
    (Identity Contract).

Identity Contract
-----------------
``canonical_claim_id`` is **script-owned**. The LLM resolver emits only
``pair_id`` (a literal ``"{claim_id_a}|{claim_id_b}"`` string copied
from the candidate list it was given). Receiving a LLM-produced
``canonical_claim_id`` is a hard invariant violation.

Failure Contract
----------------
``canonical_claim_id_for`` and the dataclass helpers never raise;
``sha1`` is a total function. IO is not exercised here — it lives in
:mod:`canonical_claim_registry`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RelationSupportKind(str, Enum):
    """How a relation is supported.

    Carried over from the broader reconciliation vocabulary (mirrors
    the canonical_models enum expected by Task 30's relation layer).
    Used by ``CanonicalClaim.support_kind`` so an aggregate can be
    tagged with the provenance of its strongest member claim.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    LLM_DIRECT = "llm_direct"
    HEURISTIC = "heuristic"


class ClaimReconciliationDecision(str, Enum):
    """Phase 2 claim-pair verdict vocabulary.

    A subset of the 8-way :py:class:`ReconciliationDecision` used by
    Phase 1. The apply order is fixed by the spec (§5.2):

        same > overlap > conflict > unresolved > single
    """

    SAME = "same"                # multiple member claims express the same view
    OVERLAP = "overlap"          # partially overlapping but not identical
    CONFLICT = "conflict"        # mutually contradictory
    UNRESOLVED = "unresolved"    # technical failure or insufficient evidence
    SINGLE = "single"            # only one member claim; no aggregation needed


# Module-level invariant — the enum is the contract.
assert len(ClaimReconciliationDecision) == 5, (
    "ClaimReconciliationDecision must have exactly 5 members; "
    "do not silently add or remove values."
)


# ---------------------------------------------------------------------------
# CanonicalClaim aggregate
# ---------------------------------------------------------------------------


@dataclass
class CanonicalClaim:
    """A canonical claim aggregates member claims across wiki pages.

    Identity Contract
    -----------------
    ``canonical_claim_id`` is script-owned (:py:func:`canonical_claim_id_for`);
    the LLM never produces it. Two claims with the same
    ``(canonical_id, text_hash, support_kind)`` collapse to the same
    ``canonical_claim_id`` — that is the Identity Contract's whole
    point: deterministic, hash-derived ids keep the LLM out of the
    naming loop.

    F4 — resolver_fingerprint
    -------------------------
    Mirrors :py:class:`CanonicalConcept.resolver_fingerprint`. Drift
    between this fingerprint and the current resolver signals that
    the canonical claim may need re-running. Task 34's
    :py:meth:`CanonicalClaimRegistry.find_stale` enforces the
    transition.

    Reversibility
    -------------
    :py:meth:`add_member_claim` and :py:meth:`remove_member_claim` are
    the only sanctioned ways to mutate ``member_claim_ids``. Both are
    idempotent. Empty memberships are preserved (the registry never
    deletes the canonical claim entity on its own).
    """

    canonical_claim_id: str                    # cc-<sha1[:12]>; script-owned, never LLM-derived
    canonical_id: str                          # the owning CanonicalConcept id
    text: str                                  # aggregate text; for Task 34 = member[0].text
    member_claim_ids: list[str] = field(default_factory=list)
    decision: ClaimReconciliationDecision = ClaimReconciliationDecision.SINGLE
    confidence: float = 0.0                    # 0..1
    support_kind: RelationSupportKind = RelationSupportKind.EXPLICIT
    created_at_ms: int = 0
    updated_at_ms: int = 0
    resolver_fingerprint: str = ""             # F4

    def add_member_claim(self, claim_id: str) -> None:
        """Idempotent: add ``claim_id`` if not already present.

        Failure Contract: never raises. Empty/whitespace inputs are
        ignored (they would never be a valid Claim.claim_id).
        """
        if not claim_id:
            return
        if claim_id not in self.member_claim_ids:
            self.member_claim_ids.append(claim_id)

    def remove_member_claim(self, claim_id: str) -> bool:
        """Remove ``claim_id`` if present. Returns ``True`` iff removed.

        Failure Contract: never raises. When the last member is removed
        the registry keeps the canonical claim record (preserves the
        id + canonical_id link for re-aggregation).
        """
        try:
            self.member_claim_ids.remove(claim_id)
        except ValueError:
            return False
        return True


# ---------------------------------------------------------------------------
# Decision record (per claim-pair)
# ---------------------------------------------------------------------------


@dataclass
class ClaimDecisionRecord:
    """A single verdict emitted by the LLM resolver (per claim-pair).

    Identity Contract
    -----------------
    ``decision_id`` is script-owned (sha1-derived). ``pair_id`` is
    copied verbatim from the LLM's output (it must equal the
    ``"{claim_id_a}|{claim_id_b}"`` form the script computed when
    enumerating pairs). The LLM never emits ``canonical_claim_id`` —
    the script generates that id at apply time via
    :py:func:`canonical_claim_id_for`.

    Evidence references
    -------------------
    ``evidence_refs`` is a free-form list (typ. claim ids or evidence
    byte ranges) the LLM used to justify its verdict. The dataclass
    doesn't validate the type — the resolver's structured-output
    schema constrains it.
    """

    decision_id: str                           # script-owned (sha1 of pair_id + canonical_id + decision)
    pair_id: str                               # "{claim_id_a}|{claim_id_b}" — script-built; LLM echoes
    canonical_id: str                          # the owning CanonicalConcept id
    decision: ClaimReconciliationDecision
    confidence: float                          # 0..1
    reason: str = ""                           # short explanation (<=30 chars per spec)
    evidence_refs: list[Any] = field(default_factory=list)
    resolver_fingerprint: str = ""
    created_at_ms: int = 0


# ---------------------------------------------------------------------------
# Script-owned id helper (Identity Contract)
# ---------------------------------------------------------------------------


def canonical_claim_id_for(
    canonical_id: str,
    text: str,
    support_kind: str,
) -> str:
    """Return a deterministic canonical-claim id: ``cc-<sha1[:12]>``.

    Hashes ``"{canonical_id}|{sha1(text)[:8]}|{support_kind}"`` and
    truncates to 12 hex chars (48 bits). Truncation is safe within a
    single canonical — collisions across unrelated canonicals are
    extremely unlikely, and a downstream audit can flag any id that
    is obviously bad.

    Parameters
    ----------
    canonical_id:
        The owning :py:class:`CanonicalConcept` id (``c-<uuid>``).
    text:
        The claim text. Only its sha1 (first 8 hex chars) is hashed;
        we never persist the raw text in the id.
    support_kind:
        String-valued :py:class:`RelationSupportKind` (``"explicit"``
        etc.). Coerced to ``""`` if not a string.

    Failure Contract: never raises. ``hashlib.sha1`` and string
    operations are total; ``str(support_kind)`` on a non-string input
    is also total.
    """
    text_hash = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8]
    identity = f"{canonical_id or ''}|{text_hash}|{str(support_kind or '')}"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"cc-{digest}"


def pair_id_for(claim_id_a: str, claim_id_b: str) -> str:
    """Return a deterministic pair id: ``"{claim_id_a}|{claim_id_b}"``.

    Order is canonicalized (lexicographic) so ``(A, B)`` and ``(B, A)``
    produce the same ``pair_id`` and the LLM's natural ordering
    doesn't matter. Empty inputs are coerced to ``""``.

    Failure Contract: never raises (string operations are total).
    """
    a = claim_id_a or ""
    b = claim_id_b or ""
    if a <= b:
        return f"{a}|{b}"
    return f"{b}|{a}"


def decision_id_for_pair(
    pair_id: str,
    canonical_id: str,
    decision: ClaimReconciliationDecision,
) -> str:
    """Return a deterministic decision id: ``dcc-<sha1[:12]>`.

    Hashes ``"{pair_id}|{canonical_id}|{decision.value}"``. Mirrors
    Phase 1's :py:func:`decision_id_for` but with a different prefix
    (``dcc-``) so the two decision logs are easy to distinguish.

    Failure Contract: never raises. Garbage inputs (None, "") are
    coerced to strings so the helper stays total.
    """
    payload = f"{pair_id or ''}|{canonical_id or ''}|{decision.value}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"dcc-{digest}"


__all__ = [
    "CanonicalClaim",
    "ClaimDecisionRecord",
    "ClaimReconciliationDecision",
    "RelationSupportKind",
    "canonical_claim_id_for",
    "pair_id_for",
    "decision_id_for_pair",
]
