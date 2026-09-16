"""Stage 6R RelationKey + RelationAssertion (Task 23).

Two related dataclasses that the rest of the v7 pipeline (Task 24
RelationStore, Task 25 LLM-direct adapter, Task 26 ClaimEvidenceRef)
build on:

* ``RelationKey`` is the canonical identity tuple for a relation —
  ``(source_page_id, predicate, target_page_id)``, with a
  ``canonical()`` that collapses symmetric edges and a
  ``relation_id()`` that derives a deterministic script-owned id.

* ``RelationAssertion`` is the runtime object that wraps a key with
  provenance / evidence / support metadata. It's the unit Task 24's
  ``RelationStore.apply_result`` persists into ``relations.jsonl``.

Identity Contract
-----------------
``RelationKey.relation_id()`` is computed purely from the canonical
triple — never from an LLM-supplied string. This keeps the relation
graph script-owned: any two runs over the same input produce identical
ids, and the rest of the pipeline can hash / dedupe without trusting
LLM output.

Failure Contract
----------------
``UNRESOLVED`` predicates are a valid input. ``canonical()`` does NOT
sort the page ids for UNRESOLVED (it's not symmetric), so the original
``source → target`` order is preserved — that way a downstream
reviewer can still tell which page the LLM intended as the source.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .relation_ontology import RelationPredicate, get_spec


# ---------------------------------------------------------------------------
# RelationKey — canonical (source, predicate, target) identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationKey:
    """Canonical triple identifying a single typed relation.

    For symmetric predicates the ``canonical()`` form sorts the page
    ids, so ``RelationKey(A, RELATED_TO, B).canonical() ==
    RelationKey(B, RELATED_TO, A).canonical()``. Directional predicates
    preserve source→target order.

    UNRESOLVED predicates are neither symmetric nor directional —
    ``canonical()`` is a no-op for them (we can't safely infer that
    the LLM's intended direction is reversible).
    """

    source_page_id: str
    predicate: RelationPredicate
    target_page_id: str

    def canonical(self) -> "RelationKey":
        """Return the symmetric-normalized form of this key.

        Symmetric predicates sort the page ids so (A,B) and (B,A)
        collapse to the same canonical triple. Directional predicates
        keep the source→target order. UNRESOLVED predicates are never
        sorted (their direction is part of the LLM's claim, even if
        the predicate itself is rejected).
        """
        spec = get_spec(self.predicate)
        if spec.symmetric:
            ordered = sorted((self.source_page_id, self.target_page_id))
            return RelationKey(ordered[0], self.predicate, ordered[1])
        return RelationKey(
            self.source_page_id, self.predicate, self.target_page_id
        )

    def relation_id(self) -> str:
        """Deterministic id derived from the canonical triple.

        Format: ``rel-<sha1(source|predicate|target)[:12]>``. The hash
        is computed over the canonical form so symmetric flips hash
        identically.
        """
        canonical = self.canonical()
        identity = (
            f"{canonical.source_page_id}|"
            f"{canonical.predicate.value}|"
            f"{canonical.target_page_id}"
        )
        digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
        return f"rel-{digest}"


# ---------------------------------------------------------------------------
# RelationSupportKind / RelationSupportStatus — provenance taxonomy
# ---------------------------------------------------------------------------


class RelationSupportKind(str, Enum):
    """How the relation entered the pipeline.

    Used by RelationStore to distinguish LLM-direct assertions from
    retrieval-derived candidates so reviewers can decide which edges
    deserve human inspection.
    """

    EXPLICIT = "explicit"          # wikilink in source body
    INFERRED = "inferred"          # retrieved candidate (entity overlap / lexical)
    LLM_DIRECT = "llm_direct"      # LLM directly asserts this edge
    HEURISTIC = "heuristic"        # rule-based (e.g. co-occurrence count)


class RelationSupportStatus(str, Enum):
    """Lifecycle / verification status of an assertion.

    Mirrors the review pipeline's three-way outcome (SUPPORTED /
    UNRESOLVED / REJECTED) so RelationStore can drop rejected edges
    without losing the audit trail.
    """

    SUPPORTED = "supported"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# RelationAssertion — runtime wrapper around RelationKey with provenance
# ---------------------------------------------------------------------------


@dataclass
class RelationAssertion:
    """A relation with full provenance / support metadata.

    The ``key`` carries the structural identity (and produces the
    ``relation_id`` via its own ``relation_id()`` method). The other
    fields capture how the edge was produced, what evidence backs it,
    and what its current review status is.

    Task 26 will extend ``evidence_refs`` to a typed list of
    ``ClaimEvidenceRef``. For now we type it as ``list[Any]`` so this
    module stays self-contained and Task 26 can substitute the
    concrete type without an import cycle.
    """

    key: RelationKey
    relation_id: str
    support_kind: RelationSupportKind
    support_status: RelationSupportStatus
    evidence_refs: list[Any] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    extractor_fingerprint: str = ""


__all__ = [
    "RelationKey",
    "RelationAssertion",
    "RelationSupportKind",
    "RelationSupportStatus",
    "RELATION_INVARIANTS",
    "RelationValidationReport",
    "validate_relation_assertions",
    "filter_substantive_relations",
    "coerce_assertion_for_known",
]


# ---------------------------------------------------------------------------
# Task 26 — Mechanical validator + 12 invariants
# ---------------------------------------------------------------------------
#
# This module grew the validator surface after Tasks 23–25 landed the data
# classes and the LLM-direct adapter. The invariants are the mechanical gate
# every ``RelationAssertion`` must pass before ``RelationStore`` (Task 24)
# accepts it; LLM garbage — invented predicates, self-loops on directional
# edges, unknown targets, empty fingerprints — is caught here, not by the
# store.
#
# Failure Contract
# ----------------
# ``validate_relation_assertions`` never raises on garbage input. Unknown
# predicates collapse to ``UNRESOLVED`` (see ``coerce_assertion_for_known``
# + ``RelationPredicate.UNRESOLVED``); assertions with at least one hard
# invariant violation land in ``report.rejected``. The caller's job is to
# feed ``report.accepted`` (and the optional ``report.unresolved`` bucket
# when it wants to preserve the audit trail of demoted edges) into the
# store and ignore ``report.rejected``.
# ---------------------------------------------------------------------------


# I1..I12 — every code a RelationAssertion can violate. Kept as a tuple so
# callers can iterate or assert count equality; ``assert len == 12`` lives
# at the bottom as a guardrail if anyone tries to silently drop or rename
# a code.
RELATION_INVARIANTS: tuple[str, ...] = (
    "I1_relation_key_fields_non_empty",        # source_page_id/predicate/target_page_id must be non-empty
    "I2_predicate_must_be_known_or_unresolved", # RelationPredicate.UNRESOLVED is allowed; everything else must be in enum
    "I3_relation_id_matches_key_canonical",     # RelationAssertion.relation_id == key.canonical().relation_id()
    "I4_self_loop_only_allowed_for_unresolved", # self.source == self.target only OK when predicate=UNRESOLVED
    "I5_directional_predicate_self_loop_rejected",  # non-UNRESOLVED + source==target → REJECTED
    "I6_target_page_must_be_known",             # target_page_id must be in all_pages set (or be a slug alias) — null target rejected
    "I7_no_duplicate_edges",                    # (source, predicate, target) dedup after canonicalize
    "I8_confidence_in_unit_range",              # 0.0 <= confidence <= 1.0
    "I9_support_kind_must_be_known",            # must be in RelationSupportKind enum
    "I10_support_status_must_be_known",         # must be in RelationSupportStatus enum
    "I11_inferred_or_heuristic_should_have_evidence",  # INFERRED/HEURISTIC with empty evidence_refs → REJECTED (LLM_DIRECT may have none)
    "I12_relation_assertion_extractor_fingerprint_set",  # empty extractor_fingerprint → REJECTED
)
assert len(RELATION_INVARIANTS) == 12


@dataclass
class RelationValidationReport:
    """Three-bucket result of ``validate_relation_assertions``.

    Attributes
    ----------
    accepted:
        ``RelationAssertion`` rows that passed all 12 invariants. These
        are the only rows ``RelationStore`` should persist.
    rejected:
        Rows that failed at least one hard invariant. Stored in the audit
        log but never made visible through the live relation view.
    unresolved:
        Rows whose predicate coerced to ``UNRESOLVED`` and that have no
        other violation. Kept separate from ``accepted`` so callers can
        decide whether to surface them (e.g. for human review) or drop
        them — they are not authoritative relations.
    violations:
        ``relation_id`` → list of ``"I<n>:<reason>"`` strings. Used by
        reviewers and the test suite to assert which invariants fired.
    """

    accepted: list[RelationAssertion] = field(default_factory=list)
    rejected: list[RelationAssertion] = field(default_factory=list)
    unresolved: list[RelationAssertion] = field(default_factory=list)
    violations: dict[str, list[str]] = field(default_factory=dict)


def validate_relation_assertions(
    assertions: list[RelationAssertion],
    *,
    known_page_ids: set[str] | None = None,
    known_aliases: dict[str, str] | None = None,
) -> RelationValidationReport:
    """Run all 12 invariants over each ``RelationAssertion``.

    Returns three buckets: ``accepted`` (clean), ``rejected`` (>=1 hard
    violation), ``unresolved`` (predicate coerced to ``UNRESOLVED`` and
    otherwise valid).

    Parameters
    ----------
    known_page_ids:
        Optional. When ``None``, invariant ``I6`` (target must be known)
        is skipped — this is the back-compat path for tests that don't
        have a page index. When provided, an unknown target triggers an
        ``I6`` violation and the assertion goes to ``rejected``.
    known_aliases:
        Optional ``alias → canonical page_id`` map. Aliases are accepted
        as long as they point to a known canonical id; the assertion's
        target id is **not** rewritten in place (use
        ``coerce_assertion_for_known`` for that). Aliases whose target
        is not in ``known_page_ids`` are treated as unknown and fail I6.
    """
    report = RelationValidationReport()

    # I7 helper: track (canonical source, predicate, canonical target)
    # triples we've already seen so a duplicate assertion after
    # canonicalization (symmetric flip) collapses to one survivor.
    seen_canonical: set[tuple[str, str, str]] = set()

    for assertion in assertions:
        rid = assertion.relation_id
        codes: list[str] = []

        # --- I1: RelationKey fields non-empty ----------------------------
        if (
            not assertion.key.source_page_id
            or not assertion.key.target_page_id
            or not isinstance(assertion.key.predicate, RelationPredicate)
        ):
            codes.append("I1:empty_key_field")

        # --- I2: predicate must be known or UNRESOLVED -------------------
        # ``RelationPredicate`` is the only authoritative predicate source;
        # a stray str (e.g. from JSON deserialization in the future) is
        # caught here. The ontology layer's ``coerce`` already collapses
        # unknown strings to UNRESOLVED for us.
        if isinstance(assertion.key.predicate, RelationPredicate):
            if assertion.key.predicate not in RelationPredicate:
                codes.append("I2:predicate_not_in_enum")

        # --- I3: relation_id matches key.canonical().relation_id() -------
        try:
            expected_rid = assertion.key.canonical().relation_id()
        except (AttributeError, TypeError):
            expected_rid = ""
        if assertion.relation_id != expected_rid:
            codes.append(f"I3:relation_id_mismatch({expected_rid})")

        # --- I4 / I5: self-loop policy -----------------------------------
        is_self_loop = (
            assertion.key.source_page_id == assertion.key.target_page_id
        )
        is_unresolved = (
            assertion.key.predicate is RelationPredicate.UNRESOLVED
        )
        if is_self_loop and not is_unresolved:
            # I5 catches the directional case (hard reject); I4 is the
            # umbrella policy statement.
            codes.append("I5:directional_self_loop_rejected")
        elif is_self_loop and is_unresolved:
            # I4 is informational only for UNRESOLVED self-loops (allowed);
            # we don't append a code, but we keep the check explicit so the
            # contract is readable.
            pass

        # --- I6: target must be known (or alias) ------------------------
        if known_page_ids is not None:
            target = assertion.key.target_page_id
            target_known = target in known_page_ids
            if not target_known and known_aliases is not None:
                alias_target = known_aliases.get(target)
                if alias_target is not None and alias_target in known_page_ids:
                    target_known = True
            if not target_known:
                codes.append(f"I6:unknown_target({assertion.key.target_page_id})")

        # --- I7: no duplicate canonical edges ----------------------------
        canonical_key = (
            assertion.key.canonical().source_page_id,
            assertion.key.canonical().predicate.value,
            assertion.key.canonical().target_page_id,
        )
        if canonical_key in seen_canonical:
            codes.append("I7:duplicate_canonical_edge")
        else:
            seen_canonical.add(canonical_key)

        # --- I8: confidence in [0.0, 1.0] --------------------------------
        try:
            conf = float(assertion.confidence)
        except (TypeError, ValueError):
            conf = float("nan")
        if conf != conf or conf < 0.0 or conf > 1.0:  # NaN-safe compare
            codes.append(f"I8:confidence_out_of_range({assertion.confidence})")

        # --- I9: support_kind must be in enum ----------------------------
        if not isinstance(assertion.support_kind, RelationSupportKind):
            codes.append(
                f"I9:support_kind_not_in_enum({assertion.support_kind!r})"
            )

        # --- I10: support_status must be in enum -------------------------
        if not isinstance(assertion.support_status, RelationSupportStatus):
            codes.append(
                f"I10:support_status_not_in_enum({assertion.support_status!r})"
            )

        # --- I11: INFERRED/HEURISTIC must have evidence_refs -------------
        if assertion.support_kind in (
            RelationSupportKind.INFERRED,
            RelationSupportKind.HEURISTIC,
        ) and not assertion.evidence_refs:
            codes.append("I11:missing_evidence_for_non_llm_kind")

        # --- I12: extractor_fingerprint must be set ----------------------
        if not (assertion.extractor_fingerprint or "").strip():
            codes.append("I12:empty_extractor_fingerprint")

        # Bucket the assertion --------------------------------------------
        if codes:
            # Stamp the rejected copy with REJECTED so downstream gates
            # (``filter_substantive_relations``, ``RelationStore``) drop
            # it on the same axis as reviewer-rejected rows. We never
            # mutate the caller's input — a new assertion is appended.
            rejected_assertion = RelationAssertion(
                key=assertion.key,
                relation_id=assertion.relation_id,
                support_kind=assertion.support_kind,
                support_status=RelationSupportStatus.REJECTED,
                evidence_refs=list(assertion.evidence_refs),
                claim_ids=list(assertion.claim_ids),
                confidence=assertion.confidence,
                extractor_fingerprint=assertion.extractor_fingerprint,
            )
            report.rejected.append(rejected_assertion)
            report.violations[rid] = codes
            continue

        if is_unresolved:
            # Predicate coerced to UNRESOLVED + no other violation →
            # unresolved bucket. This is the audit-trail home for
            # LLM-invented predicates and other demoted-but-not-broken
            # rows. We also stamp the copy's status so the unresolved
            # bucket is internally consistent (the input's status may
            # have been anything).
            unresolved_assertion = RelationAssertion(
                key=assertion.key,
                relation_id=assertion.relation_id,
                support_kind=assertion.support_kind,
                support_status=RelationSupportStatus.UNRESOLVED,
                evidence_refs=list(assertion.evidence_refs),
                claim_ids=list(assertion.claim_ids),
                confidence=assertion.confidence,
                extractor_fingerprint=assertion.extractor_fingerprint,
            )
            report.unresolved.append(unresolved_assertion)
        else:
            report.accepted.append(assertion)

    return report


def filter_substantive_relations(
    assertions: list[RelationAssertion],
) -> list[RelationAssertion]:
    """Keep only relations that may reach ``RelationStore``.

    Acceptance gate: ``support_status == SUPPORTED``. Mirrors
    ``filter_substantive_claims`` in ``claim_validator.py`` — the same
    rendering gate that prevents unsupported claims from reaching a
    rendered page is applied here to ``RelationAssertion`` rows. UNRESOLVED
    and REJECTED rows are dropped silently; order is preserved so the
    caller's deterministic order survives.
    """
    return [
        assertion
        for assertion in assertions
        if assertion.support_status is RelationSupportStatus.SUPPORTED
    ]


def coerce_assertion_for_known(
    assertion: RelationAssertion,
    *,
    known_page_ids: set[str],
    known_aliases: dict[str, str] | None = None,
) -> RelationAssertion:
    """Rewrite an LLM-direct assertion to canonical form when possible.

    Two coercions happen here:

    1. **Alias resolution.** If the target page id is in
       ``known_aliases`` and the alias maps to a known canonical id,
       the returned assertion uses the canonical id and its
       ``relation_id`` is recomputed against the canonical triple.
    2. **Predicate coercion.** If the predicate is not in
       ``RelationPredicate`` (e.g. a stray string), it is collapsed to
       ``RelationPredicate.UNRESOLVED`` and ``support_status`` is forced
       to ``UNRESOLVED`` so downstream code can spot the demotion.

    The input is never mutated — a new ``RelationAssertion`` is returned.
    If the assertion is already clean (predicate is a valid enum member
    and target is either a known page or an unresolvable alias), the
    input is returned unchanged.
    """
    target = assertion.key.target_page_id
    predicate = assertion.key.predicate

    # Predicate coercion: any non-enum value collapses to UNRESOLVED.
    if not isinstance(predicate, RelationPredicate):
        new_predicate = coerce(str(predicate))
        predicate = new_predicate
        new_status = RelationSupportStatus.UNRESOLVED
    else:
        new_status = assertion.support_status

    # Alias resolution: rewrite target to the canonical id when we know it.
    if known_aliases is not None:
        alias_target = known_aliases.get(target)
        if alias_target is not None and alias_target in known_page_ids:
            target = alias_target

    # Build a new key only when something actually changed.
    if (
        target != assertion.key.target_page_id
        or predicate is not assertion.key.predicate
        or new_status is not assertion.support_status
    ):
        new_key = RelationKey(
            source_page_id=assertion.key.source_page_id,
            predicate=predicate,
            target_page_id=target,
        )
        return RelationAssertion(
            key=new_key,
            relation_id=new_key.relation_id(),
            support_kind=assertion.support_kind,
            support_status=new_status,
            evidence_refs=list(assertion.evidence_refs),
            claim_ids=list(assertion.claim_ids),
            confidence=assertion.confidence,
            extractor_fingerprint=assertion.extractor_fingerprint,
        )
    return assertion


# Pull ``coerce`` in at runtime so the helper above doesn't add a
# top-of-module import (keeps Task 23's import surface intact).
from .relation_ontology import coerce  # noqa: E402
