"""KU → Chapter mapper (B-T2, spec §12.5 + §14 A8 step 1243).

Bridges the Knowledge Core (``KnowledgeUnit``) and the Book View
(``Chapter`` / ``KnowledgeBlock``).

Resolution order (must match §9 / A3 + B-T2 task spec):

    1. ``exact_ku_match``        confidence 1.00
       The KU's ``ku_id`` is already in ``chapter.source_knowledge_unit_ids``.

    2. ``exact_stable_key``      confidence 0.95
       A ``MappingHint(stable_key=...)`` was provided AND a chapter has that
       exact ``stable_key``.

    3. ``concept_unit_type_match``  confidence 0.85
       Derived ``stable_key = f"{ku.concept_id}::{ku.unit_type}"`` matches
       an existing chapter's ``stable_key``. This is the canonical derivation
       exposed via :func:`derive_stable_key`.

    4. ``needs_new_chapter``     confidence 0.00
       No match. Returns ``chapter_id=None`` and the derived ``stable_key`` so
       the caller can create a new chapter using the canonical derivation.

The mapper is **pure**: no I/O, no mutation, no logging side-effects. It does
NOT mutate the ``BookChapterRegistry`` or touch the knowledge core.

Spec choices documented inline:

    * Stable key derivation rule:
        ``derive_stable_key(ku) = f"{ku.concept_id}::{ku.unit_type}"``
        This matches the task spec literally. The B-T1 ``Chapter`` carries
        ``source_knowledge_unit_ids`` for exact matches; the stable_key is the
        cross-outline anchor (used by OutlineProposal migrations in later
        tasks), so deriving it from (concept, unit_type) gives the
        "concept + unit_type" mapping the spec describes.

    * Determinism: when two chapters share the same ``stable_key``, the
      FIRST occurrence in registry order wins. This matches the gold standard
      fixture ``case_013`` and ``case_032``.

    * ``proposal_threshold`` parameter: accepted for API symmetry with the
      task signature, but not consumed by the literal resolution rules. The
      mapper is binary (matches / doesn't match). Outline Proposal creation
      is the caller's responsibility (B-T3+).

No compiler, no binder, no outline engine, no renderer — those land in B-T3+.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book.contract import Chapter


# ─── Reason code vocabulary ─────────────────────────────────────────────
#
# These constants are the only allowed values for ``MappingDecision.reason``.
# Kept as a frozenset so test fixtures and downstream callers can validate
# against the same set without re-declaring the literals.

REASON_EXACT_KU_MATCH: str = "exact_ku_match"
REASON_EXACT_STABLE_KEY: str = "exact_stable_key"
REASON_CONCEPT_UNIT_TYPE_MATCH: str = "concept_unit_type_match"
REASON_NEEDS_NEW_CHAPTER: str = "needs_new_chapter"

_ALLOWED_REASONS: frozenset[str] = frozenset(
    {
        REASON_EXACT_KU_MATCH,
        REASON_EXACT_STABLE_KEY,
        REASON_CONCEPT_UNIT_TYPE_MATCH,
        REASON_NEEDS_NEW_CHAPTER,
    }
)


# ─── Stable key derivation ──────────────────────────────────────────────


def derive_stable_key(ku: KnowledgeUnit) -> str:
    """Return the canonical ``stable_key`` for a KU.

    Rule (B-T2, spec §12.5 + §14 A8):

        ``stable_key = f"{ku.concept_id}::{ku.unit_type}"``

    This is the same string callers store as ``Chapter.stable_key`` when
    creating a new chapter from a KU, so future calls to
    :func:`map_ku_to_chapter` can match by derivation
    (``concept_unit_type_match``).
    """
    return f"{ku.concept_id}::{ku.unit_type}"


# ─── Result + helper dataclasses ────────────────────────────────────────


@dataclass(frozen=True)
class MappingDecision:
    """Result of one mapping attempt.

    Fields:
        chapter_id   ``str | None`` — matched Chapter id, or ``None`` when
                      ``reason == "needs_new_chapter"``.
        stable_key   ``str``        — the matched Chapter's ``stable_key``,
                      or the canonical derivation (see :func:`derive_stable_key`)
                      when ``reason == "needs_new_chapter"`` and the caller
                      will create the new chapter using that key.
        confidence   ``float``      — 0.0–1.0, see resolution order above.
        reason       ``str``        — one of the four reason codes; see
                      :data:`_ALLOWED_REASONS`.
    """

    chapter_id: str | None
    stable_key: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class MappingHint:
    """Optional hint provided by the caller to steer mapping.

    Today only ``stable_key`` is honored (the ``exact_stable_key`` step).
    Other fields may be added later (e.g. ``template_hint``).
    """

    stable_key: str | None = None


@dataclass(frozen=True)
class BookChapterRegistry:
    """Immutable view of the chapters in a Book, with lookup helpers.

    The mapper reads from this registry but never mutates it. Construction
    normalizes the input to a tuple so the registry is hashable and the
    chapters are read-only by convention.

    Fields:
        chapters  ``tuple[Chapter, ...]`` — ordered (matches Book.chapter_ids).
    """

    chapters: tuple[Chapter, ...]

    def __post_init__(self) -> None:
        # Normalize to tuple so external list mutation cannot affect us.
        if not isinstance(self.chapters, tuple):
            object.__setattr__(self, "chapters", tuple(self.chapters))

    # ── Finders ──

    def find_by_stable_key(self, stable_key: str) -> Chapter | None:
        """Return the FIRST chapter whose ``stable_key`` matches, else None.

        Determinism matters when two chapters share a ``stable_key`` (e.g.
        during an in-flight Outline Proposal migration).
        """
        for ch in self.chapters:
            if ch.stable_key == stable_key:
                return ch
        return None

    def find_by_ku_id(self, ku_id: str) -> Chapter | None:
        """Return the FIRST chapter whose ``source_knowledge_unit_ids``
        contains ``ku_id``, else None. Used by ``exact_ku_match``.
        """
        for ch in self.chapters:
            if ku_id in ch.source_knowledge_unit_ids:
                return ch
        return None

    def find_by_concept_id(
        self, concept_id: str, unit_type: str | None = None
    ) -> Chapter | None:
        """Return the FIRST chapter whose DERIVED stable_key matches
        ``f"{concept_id}::{unit_type or anything}"``.

        With ``unit_type=None`` this is a "concept-only" search — every
        chapter for the concept matches. Currently informational; the
        :func:`map_ku_to_chapter` resolution uses the explicit derivation
        via :func:`derive_stable_key` (which always carries ``unit_type``).
        """
        if unit_type is None:
            for ch in self.chapters:
                if ch.stable_key.startswith(f"{concept_id}::"):
                    return ch
            return None
        return self.find_by_stable_key(derive_stable_key(
            KnowledgeUnit(
                ku_id="__concept_lookup__",
                concept_id=concept_id,
                question="",
                title="",
                unit_type=unit_type,  # type: ignore[arg-type]
            )
        ))


# ─── Primary entry point ────────────────────────────────────────────────


def map_ku_to_chapter(
    ku: KnowledgeUnit,
    chapter_registry: BookChapterRegistry,
    *,
    hint: MappingHint | None = None,
    proposal_threshold: int = 1,
) -> MappingDecision:
    """Decide which ``Chapter`` should host a ``KnowledgeBlock`` for ``ku``.

    Args:
        ku                 Source ``KnowledgeUnit`` from Knowledge Core.
        chapter_registry   Immutable view of the Book's existing chapters.
        hint               Optional :class:`MappingHint` (currently only
                           ``stable_key`` is honored). Use to steer mapping
                           when the caller already knows the target stable_key
                           (e.g. from a previous Outline Proposal).
        proposal_threshold Accepted for API symmetry with the B-T2 task
                           signature. The literal resolution rules are
                           binary; Outline Proposal creation lives in B-T3+.

    Returns:
        :class:`MappingDecision`. When ``reason == "needs_new_chapter"``,
        ``chapter_id`` is ``None`` and ``stable_key`` carries the canonical
        derivation the caller can use to create a new chapter.

    Resolution order (strict):

        1. ``exact_ku_match``        (confidence 1.00)
        2. ``exact_stable_key``      (confidence 0.95, requires ``hint``)
        3. ``concept_unit_type_match`` (confidence 0.85, via
           :func:`derive_stable_key`)
        4. ``needs_new_chapter``     (confidence 0.00)

    Pure function. No I/O, no mutation, no logging.
    """
    derived = derive_stable_key(ku)

    # ── 1. exact_ku_match ──────────────────────────────────────────────
    matched = chapter_registry.find_by_ku_id(ku.ku_id)
    if matched is not None:
        return MappingDecision(
            chapter_id=matched.id,
            stable_key=matched.stable_key,
            confidence=1.0,
            reason=REASON_EXACT_KU_MATCH,
        )

    # ── 2. exact_stable_key (only if a hint was provided) ──────────────
    if hint is not None and hint.stable_key:
        matched = chapter_registry.find_by_stable_key(hint.stable_key)
        if matched is not None:
            return MappingDecision(
                chapter_id=matched.id,
                stable_key=matched.stable_key,
                confidence=0.95,
                reason=REASON_EXACT_STABLE_KEY,
            )

    # ── 3. concept_unit_type_match ─────────────────────────────────────
    matched = chapter_registry.find_by_stable_key(derived)
    if matched is not None:
        return MappingDecision(
            chapter_id=matched.id,
            stable_key=matched.stable_key,
            confidence=0.85,
            reason=REASON_CONCEPT_UNIT_TYPE_MATCH,
        )

    # ── 4. needs_new_chapter ───────────────────────────────────────────
    return MappingDecision(
        chapter_id=None,
        stable_key=derived,
        confidence=0.0,
        reason=REASON_NEEDS_NEW_CHAPTER,
    )


__all__ = [
    "BookChapterRegistry",
    "MappingDecision",
    "MappingHint",
    "REASON_CONCEPT_UNIT_TYPE_MATCH",
    "REASON_EXACT_KU_MATCH",
    "REASON_EXACT_STABLE_KEY",
    "REASON_NEEDS_NEW_CHAPTER",
    "derive_stable_key",
    "map_ku_to_chapter",
]
