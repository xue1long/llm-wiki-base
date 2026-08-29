"""bind_evidence + EvidenceRef (B-T3a, spec §12.5 + §14 A8 step 1244).

Roadmap §12.5 (Book Contract) + §14 A8 step 1244 (Evidence Binder):

This module is the **pure-function layer** that resolves a
``KnowledgeBlock``'s ``evidence_refs`` (a list of evidence_id strings per
B-T1 Contract) into a tuple of ``EvidenceRef`` snapshots.

Why a snapshot instead of live ``Evidence`` references? Because the Chapter
Render outlives the ``KnowledgeCoreView`` — once the render is staged the
view can be garbage-collected, but the rendering payload must still carry
the exact text + provenance it was rendered from. The ``EvidenceRef`` is
that payload.

Strictness (B-T3 spec):

    * Any evidence_id NOT found in ``core_view`` → raise ``ValueError``
      listing the missing IDs. B-T3 is strict because an Unsupported Fact
      must NEVER appear in the published chapter (Gate A8 "Unsupported Fact
      = 0").
    * Dedup: if the same evidence_id appears multiple times in
      ``block.evidence_refs``, only the first occurrence wins (preserve
      order).
    * ``strength`` / ``evidence_type`` come from the ``Evidence`` value
      object directly — do NOT recompute.
    * Empty ``block.evidence_refs`` → return ``()`` (a block with no facts is
      structurally valid).

B-T3a ``strength`` placeholder:

    The ``Evidence`` dataclass (src/kc/contracts/evidence.py) does NOT carry
    a ``strength`` field — it has ``evidence_type`` and ``confidence``
    instead. Per the task spec we default ``EvidenceRef.strength`` to
    ``"medium"`` for B-T3a. The StrengthPolicy lives in
    ``src/kc/contracts/strength_policy.py`` and B-T3b will integrate it:

        TODO(B-T3b): replace the literal ``"medium"`` default with the
        StrengthPolicy computation. Until then, every EvidenceRef carries
        strength="medium".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.kc.views.book.contract import KnowledgeBlock
from src.kc.views.book.core_view import KnowledgeCoreView


# Allowed vocabularies mirror src/kc/contracts/evidence.py. Repeated here as
# Literal[...] so the EvidenceRef dataclass is self-contained (it carries its
# own type contract; the Evidence module remains the runtime source of truth).
EvidenceRefStrength = Literal["strong", "medium", "weak"]
EvidenceRefType = Literal[
    "direct_quote",
    "structured_source",
    "code",
    "computed",
    "multi_source",
    "inferred",
]


@dataclass(frozen=True)
class EvidenceRef:
    """Block → evidence 绑定的最小回溯单元.

    Mirrors the relevant fields of ``Evidence`` but as a self-contained
    snapshot (so the binding survives after the ``core_view`` goes away —
    the Chapter Render needs to outlive the view).

    Fields:

        evidence_id     Stable Evidence identifier (mirrors
                        ``Evidence.evidence_id``).
        strength        One of ``"strong" | "medium" | "weak"``.
        evidence_type   One of the 6 spec §5.7 evidence types.
        quote           Verbatim quote text the renderer cites.
        quote_hash      SHA-256 of the quote (``Evidence.quote_hash``).
        document_id     Owning canonical document.
        block_id        Owning block within the document.

    ``strength`` placeholder note:

        The ``Evidence`` value object does not currently carry a strength
        field. For B-T3a we default every ``EvidenceRef.strength`` to
        ``"medium"``. B-T3b will integrate ``StrengthPolicy``
        (``src/kc/contracts/strength_policy.py``) and replace this default
        with the real computation. The field is preserved on the dataclass
        so the contract is stable across tasks.

    Frozen dataclass guarantees the snapshot is immutable once bound — see
    ``tests/test_kc/test_book_binder.py::test_evidence_ref_is_frozen_…``.
    """

    evidence_id: str
    strength: EvidenceRefStrength
    evidence_type: EvidenceRefType
    quote: str
    quote_hash: str
    document_id: str
    block_id: str


def bind_evidence(
    block: KnowledgeBlock,
    core_view: KnowledgeCoreView,
) -> tuple[EvidenceRef, ...]:
    """Resolve ``block.evidence_refs`` into a tuple of ``EvidenceRef``
    snapshots.

    Pure function — no I/O, no mutation, no logging.

    Strictness (B-T3 spec):

        * Any evidence_id not in ``core_view`` → raise ``ValueError``
          listing ALL missing IDs. Atomic: no partial binding is returned.
        * Dedup by evidence_id (first occurrence wins, order preserved).
        * ``evidence_type`` is read verbatim from the backing ``Evidence``;
          do not recompute.
        * ``strength`` defaults to ``"medium"`` for every ref in B-T3a
          (see EvidenceRef docstring).

    Args:
        block:       The ``KnowledgeBlock`` whose ``evidence_refs`` to bind.
        core_view:   The ``KnowledgeCoreView`` to resolve evidence from.

    Returns:
        ``tuple[EvidenceRef, ...]`` in the order of the (deduped) input.
        Empty tuple when ``block.evidence_refs`` is empty.

    Raises:
        ValueError: if any evidence_id in ``block.evidence_refs`` is not
            resolvable through ``core_view``. The error message lists every
            missing id so the caller can fix the block in one round-trip.
    """
    raw_ids = block.evidence_refs
    if not raw_ids:
        return ()

    # Dedup — first occurrence wins, order preserved.
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for eid in raw_ids:
        if eid not in seen:
            seen.add(eid)
            ordered_ids.append(eid)

    # Resolve everything before constructing any EvidenceRef so a missing id
    # can never produce a partial binding.
    missing: list[str] = []
    resolved: list[tuple[str, object]] = []
    for eid in ordered_ids:
        evidence = core_view.get_evidence(eid)
        if evidence is None:
            missing.append(eid)
            continue
        resolved.append((eid, evidence))

    if missing:
        raise ValueError(
            f"bind_evidence: evidence ids not found in core_view "
            f"{missing} (block_id={block.id!r}, requested={list(raw_ids)})"
        )

    return tuple(
        EvidenceRef(
            evidence_id=eid,
            # TODO(B-T3b): replace with StrengthPolicy.compute(evidence).
            # B-T3a placeholder — Evidence has no strength field today.
            strength="medium",
            evidence_type=evidence.evidence_type,  # type: ignore[union-attr]
            quote=evidence.quote,  # type: ignore[union-attr]
            quote_hash=evidence.quote_hash,  # type: ignore[union-attr]
            document_id=evidence.document_id,  # type: ignore[union-attr]
            block_id=evidence.block_id,  # type: ignore[union-attr]
        )
        for eid, evidence in resolved
    )


__all__ = [
    "EvidenceRef",
    "EvidenceRefStrength",
    "EvidenceRefType",
    "bind_evidence",
]
