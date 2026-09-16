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
]
