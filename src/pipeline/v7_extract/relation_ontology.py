"""Stage 6R RelationPredicate ontology (Task 23).

This module is the authoritative source for which predicate strings the
rest of the v7 pipeline is allowed to reason about. Two rules govern it:

  1. The enum lists every predicate the LLM is allowed to return, plus
     one synthetic ``UNRESOLVED`` member that swallows anything else.
     (12 substantive predicates — 8 directional + 4 symmetric — plus
     the UNRESOLVED catch-all = 13 members total.)
  2. The companion ``RelationTypeSpec`` table records the structural
     shape of each predicate (directional vs. symmetric, inverse,
     high-risk flag) so callers don't reinvent these decisions.

Downstream (Task 24 RelationStore, Task 25 LLM-direct adapter, Task 26
ClaimEvidenceRef) consume the spec dict directly — adding a predicate is
a one-line edit here, not a refactor across the pipeline.

Identity Contract
-----------------
``relation_id`` is derived purely from the predicate's string value
(see ``relation_models.RelationKey``). We never embed an LLM-provided
id into the ontology; the enum value is the only authority.

Failure Contract
----------------
``UNRESOLVED`` is a valid, expected status — not an exception path.
``coerce()`` always returns a ``RelationPredicate`` (never raises on
garbage input); ``is_known()`` distinguishes substantive predicates
from ``UNRESOLVED`` / garbage so callers can decide whether to drop,
demote, or surface the relation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RelationPredicate(str, Enum):
    """Substantive predicates + an UNRESOLVED catch-all.

    Members are string-valued so ``RelationPredicate("refines") ==
    RelationPredicate.REFINES`` round-trips through JSON / frontmatter
    without any custom (de)serialization.
    """

    # ---- directional: source→target order is meaningful -----------------
    REFINES = "refines"
    SUPPORTED_BY = "supported_by"
    CAUSES = "causes"
    REQUIRES = "requires"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    INSTANCE_OF = "instance_of"

    # ---- symmetric: source↔target order is interchangeable --------------
    RELATED_TO = "related_to"
    SIMILAR_TO = "similar_to"
    CO_OCCURS_WITH = "co_occurs_with"
    PAIRED_WITH = "paired_with"

    # ---- catch-all for any predicate the LLM produces that we don't
    # recognize. Not "known" — see ``is_known`` below.
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class RelationTypeSpec:
    """Structural shape of a ``RelationPredicate``.

    Attributes
    ----------
    predicate:
        The enum member this spec describes.
    directional:
        True iff ``source → target`` carries different meaning than
        ``target → source``. Always True for directional predicates,
        always False for symmetric ones. ``UNRESOLVED`` is neither
        (directional=False, symmetric=False) because we can't make
        structural assumptions about an unknown predicate.
    symmetric:
        True iff the predicate is unordered — (A,B) and (B,A) denote
        the same edge. RelationKey.canonical() sorts the page ids for
        symmetric specs to dedupe flipped edges.
    inverse_predicate:
        For directional predicates, the predicate that reads the edge
        in the opposite direction (e.g. ``supports`` is the inverse of
        ``supported_by``). ``UNRESOLVED`` and symmetric predicates fill
        this with the predicate itself (no inverse).
    high_risk:
        True iff the LLM should self-review an edge with this
        predicate before accepting it (e.g. ``contradicts``, ``causes``
        change the reader's interpretation of the source page).
    """

    predicate: RelationPredicate
    directional: bool
    symmetric: bool
    inverse_predicate: "RelationPredicate"
    high_risk: bool


# ---------------------------------------------------------------------------
# Spec table — one row per RelationPredicate member.
#
# Keep the dict in the same order as the enum (directional first, then
# symmetric, then UNRESOLVED) so a debugger scan reads top-to-bottom.
# ---------------------------------------------------------------------------

_RELATION_SPECS: dict[RelationPredicate, RelationTypeSpec] = {
    RelationPredicate.REFINES: RelationTypeSpec(
        predicate=RelationPredicate.REFINES,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=False,
    ),
    RelationPredicate.SUPPORTED_BY: RelationTypeSpec(
        predicate=RelationPredicate.SUPPORTED_BY,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=False,
    ),
    RelationPredicate.CAUSES: RelationTypeSpec(
        predicate=RelationPredicate.CAUSES,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=True,
    ),
    RelationPredicate.REQUIRES: RelationTypeSpec(
        predicate=RelationPredicate.REQUIRES,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=True,
    ),
    RelationPredicate.CONTRADICTS: RelationTypeSpec(
        predicate=RelationPredicate.CONTRADICTS,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.CONTRADICTS,
        high_risk=True,
    ),
    RelationPredicate.EXTENDS: RelationTypeSpec(
        predicate=RelationPredicate.EXTENDS,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=False,
    ),
    RelationPredicate.DEPENDS_ON: RelationTypeSpec(
        predicate=RelationPredicate.DEPENDS_ON,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=True,
    ),
    RelationPredicate.INSTANCE_OF: RelationTypeSpec(
        predicate=RelationPredicate.INSTANCE_OF,
        directional=True,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=False,
    ),
    RelationPredicate.RELATED_TO: RelationTypeSpec(
        predicate=RelationPredicate.RELATED_TO,
        directional=False,
        symmetric=True,
        inverse_predicate=RelationPredicate.RELATED_TO,
        high_risk=False,
    ),
    RelationPredicate.SIMILAR_TO: RelationTypeSpec(
        predicate=RelationPredicate.SIMILAR_TO,
        directional=False,
        symmetric=True,
        inverse_predicate=RelationPredicate.SIMILAR_TO,
        high_risk=False,
    ),
    RelationPredicate.CO_OCCURS_WITH: RelationTypeSpec(
        predicate=RelationPredicate.CO_OCCURS_WITH,
        directional=False,
        symmetric=True,
        inverse_predicate=RelationPredicate.CO_OCCURS_WITH,
        high_risk=False,
    ),
    RelationPredicate.PAIRED_WITH: RelationTypeSpec(
        predicate=RelationPredicate.PAIRED_WITH,
        directional=False,
        symmetric=True,
        inverse_predicate=RelationPredicate.PAIRED_WITH,
        high_risk=False,
    ),
    RelationPredicate.UNRESOLVED: RelationTypeSpec(
        predicate=RelationPredicate.UNRESOLVED,
        directional=False,
        symmetric=False,
        inverse_predicate=RelationPredicate.UNRESOLVED,
        high_risk=True,
    ),
}


def get_spec(predicate: RelationPredicate) -> RelationTypeSpec:
    """Return the ``RelationTypeSpec`` for ``predicate``.

    Always succeeds: every enum member has a row in ``_RELATION_SPECS``,
    so this never raises KeyError. The only fallback we honor is the
    case where a caller passes an enum-valued argument from a forked
    definition — in that scenario we fall back to ``UNRESOLVED`` rather
    than raise, to keep the Failure Contract "never raise on unknown
    predicate" promise at the boundary.
    """
    spec = _RELATION_SPECS.get(predicate)
    if spec is None:
        return _RELATION_SPECS[RelationPredicate.UNRESOLVED]
    return spec


def is_known(predicate: str) -> bool:
    """True iff ``predicate`` is a substantive (non-UNRESOLVED) predicate.

    Garbage strings return False; UNRESOLVED itself returns False (the
    caller's signal to demote or drop the relation).
    """
    try:
        member = RelationPredicate(predicate)
    except ValueError:
        return False
    return member is not RelationPredicate.UNRESOLVED


def coerce(predicate: str) -> RelationPredicate:
    """Map any string to a ``RelationPredicate``.

    Unknown predicates collapse to ``RelationPredicate.UNRESOLVED`` rather
    than raising — this is the Failure Contract promise for the ontology
    boundary. Callers that need to drop garbage entirely should pair this
    with ``is_known()``.
    """
    try:
        return RelationPredicate(predicate)
    except ValueError:
        return RelationPredicate.UNRESOLVED


__all__ = [
    "RelationPredicate",
    "RelationTypeSpec",
    "get_spec",
    "is_known",
    "coerce",
]
