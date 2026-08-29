"""KnowledgeCoreView Protocol + SimpleKnowledgeCoreView default impl (B-T3a).

Roadmap §12.5 (Book Contract) + §14 A8 step 1244:

The KnowledgeCoreView is the read-only surface the Book Compiler reads
from. B-T3a defines the Protocol + a tiny in-memory default; B-T3b will
plug ``compile_chapter`` into it.

Design choices (B-T3a):

    * The Protocol is **structural** (``typing.Protocol`` with no ``runtime_checkable``).
      Callers use static type-checking for protocol conformance; the default
      in-memory implementation is the only one we ship today, and a future
      JSONL-backed or service-backed implementation only needs to implement
      the same five methods.

    * ``get_claim`` returns ``Any`` (not a Claim class). The Claim type is
      not in the KC namespace and forcing this Protocol to depend on it would
      couple Book compilation to claim implementation choices.

    * ``current_publication_version`` returns an int — the value Book views
      MUST consume (spec §17 D-21). The default impl defaults to ``0`` so
      empty views still satisfy the contract.

    * ``kus_for_chapter`` is STRICT — any missing KU id raises ``ValueError``.
      This is B-T3 spec: a Chapter that can't resolve its source KUs cannot
      be compiled. Empty ``source_knowledge_unit_ids`` returns ``()``
      (placeholder chapters are valid).
"""
from __future__ import annotations

from typing import Any, Protocol

from src.kc.contracts.evidence import Evidence
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book.contract import Chapter


class KnowledgeCoreView(Protocol):
    """Read-only view of the Knowledge Core for Book compilation.

    B-T3a only; B-T3b will exercise this via ``compile_chapter``.

    All methods are pure (no mutation, no I/O). Implementations may back
    this with any store (in-memory dict, real JSONL, mocked service, etc.) —
    the Protocol does not care.

    This Protocol is intentionally NOT ``@runtime_checkable``: structural
    subtyping is sufficient for static type-checking, and runtime
    ``isinstance`` checks would force every alternative implementation to
    also be ``@runtime_checkable`` — which is not worth the constraint for
    B-T3a. If a future task needs runtime dispatch on the Protocol, that
    task can flip the decorator with a single one-line change.
    """

    def get_ku(self, ku_id: str) -> KnowledgeUnit | None:
        """Return the KU or ``None`` if not found."""

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return the Evidence or ``None`` if not found."""

    def get_claim(self, claim_id: str) -> Any | None:
        """Return a Claim (any duck-typed object) or ``None``. Claim is NOT
        in the KC namespace — the return type is ``Any`` to keep this Protocol
        decoupled from claim implementation choices."""

    def current_publication_version(self) -> int:
        """Return the currently-active publication_version from the Core's
        PublicationGate. Book views MUST read this rather than invent their
        own version counter (spec §17 D-21)."""

    def kus_for_chapter(self, chapter: Chapter) -> tuple[KnowledgeUnit, ...]:
        """Batch-fetch all KUs referenced by
        ``chapter.source_knowledge_unit_ids`` in order.

        * Raises ``ValueError`` if any ku_id is missing (B-T3 strict).
        * Returns empty tuple if chapter has no source KUs.
        """

    def ku_evidence_ids(self, ku_id: str) -> tuple[str, ...]:
        """Return the evidence ids backing the given KU.

        B-T3.5 (B-T3b Important-fix): the canonical place where the
        Knowledge Core exposes the KU ↔ Evidence mapping. Returns
        empty tuple when the KU has no evidence or is unknown —
        callers handle absence (compile_chapter treats empty as
        ``unsupported_fact=True`` for that block, which is the
        correct semantic — a block with no evidence IS an unsupported
        fact).
        """


class SimpleKnowledgeCoreView:
    """In-memory ``KnowledgeCoreView`` for testing + B-T3b compilation.

    Backs every method with simple dicts. Intended for unit tests and as a
    seed for future real implementations (e.g. JSONL-backed view).

    Strictness contract (documented for every method):

        * ``get_ku`` / ``get_evidence`` / ``get_claim`` — missing → return
          ``None`` (callers handle absence).
        * ``kus_for_chapter`` — missing → raise ``ValueError`` (B-T3 strict:
          a Chapter that can't resolve its source KUs cannot be compiled).
        * ``current_publication_version`` — returns the stored ``int``
          verbatim.

    Construction keyword-only so the API is unambiguous as it grows:

        * ``kus``             ``dict[str, KnowledgeUnit]``
        * ``evidences``       ``dict[str, Evidence]``
        * ``claims``          ``dict[str, Any]``  (duck-typed)
        * ``publication_version``  ``int``
    """

    def __init__(
        self,
        *,
        kus: dict[str, KnowledgeUnit] | None = None,
        evidences: dict[str, Evidence] | None = None,
        claims: dict[str, Any] | None = None,
        ku_evidence_map: dict[str, tuple[str, ...]] | None = None,
        publication_version: int = 0,
    ) -> None:
        self.kus: dict[str, KnowledgeUnit] = dict(kus or {})
        self.evidences: dict[str, Evidence] = dict(evidences or {})
        self.claims: dict[str, Any] = dict(claims or {})
        self.ku_evidence_map: dict[str, tuple[str, ...]] = dict(ku_evidence_map or {})
        self.publication_version: int = int(publication_version)

    # ── Single-item lookups — missing → None ─────────────────────────────

    def get_ku(self, ku_id: str) -> KnowledgeUnit | None:
        """Return the KU registered under ``ku_id`` or ``None`` if absent."""
        return self.kus.get(ku_id)

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Return the Evidence registered under ``evidence_id`` or ``None``."""
        return self.evidences.get(evidence_id)

    def get_claim(self, claim_id: str) -> Any | None:
        """Return the duck-typed claim registered under ``claim_id`` or
        ``None``. ``Any`` is intentional — see Protocol docstring."""
        return self.claims.get(claim_id)

    # ── Publication version (spec §17 D-21) ──────────────────────────────

    def current_publication_version(self) -> int:
        """Return the stored publication_version verbatim."""
        return self.publication_version

    # ── Batch lookup — missing → ValueError ──────────────────────────────

    def kus_for_chapter(self, chapter: Chapter) -> tuple[KnowledgeUnit, ...]:
        """Batch-fetch the KUs referenced by ``chapter.source_knowledge_unit_ids``.

        Order matches the chapter's list. Empty input → empty tuple.
        Missing ku_id → ``ValueError`` (atomic — no partial result returned).
        """
        ids = chapter.source_knowledge_unit_ids
        if not ids:
            return ()
        missing = [ku_id for ku_id in ids if ku_id not in self.kus]
        if missing:
            raise ValueError(
                f"SimpleKnowledgeCoreView.kus_for_chapter: missing KU ids "
                f"{missing} (chapter_id={chapter.id!r}, expected={list(ids)})"
            )
        return tuple(self.kus[ku_id] for ku_id in ids)

    # ── Per-KU evidence wiring (B-T3.5) ──────────────────────────────────

    def ku_evidence_ids(self, ku_id: str) -> tuple[str, ...]:
        """Return the evidence ids for ``ku_id`` or empty tuple.

        Missing KU id (or KU with no evidence) → empty tuple.
        Caller is responsible for treating empty as a signal that
        the block is unsupported.
        """
        return self.ku_evidence_map.get(ku_id, ())


__all__ = [
    "KnowledgeCoreView",
    "SimpleKnowledgeCoreView",
]
