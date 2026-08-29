"""Tests for bind_evidence (B-T3a, spec §12.5 + §14 A8 step 1244).

Layer: pure-function tests over a frozen ``Evidence``-backed
``SimpleKnowledgeCoreView`` plus ``KnowledgeBlock`` fixtures.

Coverage (B-T3a scope — pure binder only):

    1.  happy path: 3 evidence IDs in block, all found → 3-tuple, order preserved
    2.  dedup: same ID twice → 1-tuple (first wins)
    3.  empty block.evidence_refs → ()
    4.  missing evidence_id → ValueError listing the missing ID
    5.  multiple missing IDs → ValueError lists ALL of them
    6.  mixed (some found, some missing) → ValueError (atomic binding)
    7.  quote / quote_hash / document_id / block_id passed through
    8.  evidence_type preserved verbatim
    9.  strength defaults to "medium" (B-T3a placeholder until StrengthPolicy)
    10. frozen dataclass: EvidenceRef cannot be mutated after creation
    11. same evidence_id in two blocks → independent binds, no shared state
    12. empty core_view + non-empty block.evidence_refs → ValueError

NO compiler / IntegrityGate tests — those land in B-T3b.
"""
from __future__ import annotations

import pytest

# Imports intentionally fail before implementation — TDD red phase.
from src.kc.contracts.evidence import Evidence
from src.kc.views.book import (
    KnowledgeBlock,
    KnowledgeBlockType,
)
from src.kc.views.book.binder import (
    EvidenceRef,
    bind_evidence,
)
from src.kc.views.book.core_view import SimpleKnowledgeCoreView


# ─── Helpers ─────────────────────────────────────────────────────────────


def _evidence(
    *,
    evidence_id: str = "ev_aaaa0000_x",
    document_id: str = "doc_11111111_y",
    block_id: str = "block_22222222_z",
    quote: str = "default quote",
    quote_hash: str = "0" * 64,
    evidence_type: str = "direct_quote",
    confidence: float = 0.9,
) -> Evidence:
    """Build an Evidence with sensible defaults; tests override what matters."""
    return Evidence(
        evidence_id=evidence_id,
        document_id=document_id,
        block_id=block_id,
        quote=quote,
        quote_hash=quote_hash,
        evidence_type=evidence_type,
        confidence=confidence,
    )


def _core_view(*evidences: Evidence) -> SimpleKnowledgeCoreView:
    """Build a SimpleKnowledgeCoreView preloaded with the given Evidence items."""
    return SimpleKnowledgeCoreView(
        evidences={e.evidence_id: e for e in evidences},
    )


def _block(
    *,
    evidence_refs: list[str] | None = None,
    block_type: KnowledgeBlockType = KnowledgeBlockType.DEFINITION,
) -> KnowledgeBlock:
    """Build a KnowledgeBlock; defaults to a definition block with no evidence."""
    return KnowledgeBlock(
        id="kb_bbbb0000_b",
        chapter_id="ch_cccc0000_c",
        block_type=block_type,
        evidence_refs=list(evidence_refs or []),
    )


# ─── 1. happy path ───────────────────────────────────────────────────────


def test_happy_path_three_evidence_refs_returns_three_evidence_refs_in_order():
    """Three distinct evidence IDs all present → tuple of three EvidenceRef
    snapshots, preserving the order from ``block.evidence_refs``."""
    ev1 = _evidence(evidence_id="ev_first", quote="first quote", quote_hash="a" * 64)
    ev2 = _evidence(evidence_id="ev_second", quote="second quote", quote_hash="b" * 64)
    ev3 = _evidence(evidence_id="ev_third", quote="third quote", quote_hash="c" * 64)
    cv = _core_view(ev1, ev2, ev3)

    block = _block(evidence_refs=["ev_first", "ev_second", "ev_third"])

    refs = bind_evidence(block, cv)

    assert isinstance(refs, tuple)
    assert len(refs) == 3
    assert refs[0].evidence_id == "ev_first"
    assert refs[1].evidence_id == "ev_second"
    assert refs[2].evidence_id == "ev_third"


# ─── 2. dedup ────────────────────────────────────────────────────────────


def test_dedup_same_evidence_id_twice_returns_one_entry():
    """If the same evidence_id appears multiple times in
    ``block.evidence_refs``, only the first occurrence wins. Order preserved.
    """
    ev = _evidence(evidence_id="ev_dup", quote="only one quote", quote_hash="d" * 64)
    cv = _core_view(ev)
    block = _block(evidence_refs=["ev_dup", "ev_dup", "ev_dup"])

    refs = bind_evidence(block, cv)

    assert len(refs) == 1
    assert refs[0].evidence_id == "ev_dup"


# ─── 3. empty block.evidence_refs ────────────────────────────────────────


def test_empty_evidence_refs_returns_empty_tuple():
    """Block with no evidence refs (a structural / placeholder block) is valid
    and produces an empty tuple — the block has no facts to support."""
    cv = _core_view(_evidence(evidence_id="ev_present"))
    block = _block(evidence_refs=[])

    refs = bind_evidence(block, cv)

    assert refs == ()


# ─── 4. single missing evidence_id → ValueError ─────────────────────────


def test_missing_evidence_id_raises_value_error_with_id_in_message():
    """Strict binding: an evidence_id not in core_view → ValueError that
    names the missing id (so the caller can render an actionable message)."""
    cv = _core_view()  # empty core_view
    block = _block(evidence_refs=["ev_missing_001"])

    with pytest.raises(ValueError) as excinfo:
        bind_evidence(block, cv)

    assert "ev_missing_001" in str(excinfo.value)


# ─── 5. multiple missing IDs all listed ─────────────────────────────────


def test_multiple_missing_evidence_ids_all_listed_in_error():
    """When multiple IDs are missing, the error must list ALL of them so the
    caller can fix the block in one round-trip."""
    cv = _core_view(_evidence(evidence_id="ev_present"))
    block = _block(evidence_refs=["ev_missing_a", "ev_present", "ev_missing_b"])

    with pytest.raises(ValueError) as excinfo:
        bind_evidence(block, cv)

    msg = str(excinfo.value)
    assert "ev_missing_a" in msg
    assert "ev_missing_b" in msg


# ─── 6. mixed → atomic (no partial binding) ──────────────────────────────


def test_mixed_found_and_missing_raises_no_partial_binding():
    """When at least one evidence_id is missing, the entire bind is rejected
    with ValueError — there is NO partial binding returned to the caller.
    (Verified structurally: the function only has two return paths — ``()`` or
    a tuple of EvidenceRefs — so a ValueError cannot coexist with a partial
    return.)"""
    cv = _core_view(_evidence(evidence_id="ev_present", quote="kept"))
    block = _block(evidence_refs=["ev_present", "ev_missing"])

    with pytest.raises(ValueError):
        bind_evidence(block, cv)

    # Stronger guarantee — when called again on the same input, behavior is
    # identical (pure function).
    with pytest.raises(ValueError):
        bind_evidence(block, cv)


# ─── 7. passthrough: quote / quote_hash / document_id / block_id ────────


def test_evidence_ref_carries_quote_quote_hash_document_id_block_id():
    """EvidenceRef snapshots every field needed by the Chapter Render to
    survive after core_view is gone."""
    cv = _core_view(
        _evidence(
            evidence_id="ev_passthrough",
            quote="the specific quote",
            quote_hash="f" * 64,
            document_id="doc_aaaaaaaa",
            block_id="block_bbbbbbbb",
        )
    )
    block = _block(evidence_refs=["ev_passthrough"])

    refs = bind_evidence(block, cv)

    assert len(refs) == 1
    ref = refs[0]
    assert ref.quote == "the specific quote"
    assert ref.quote_hash == "f" * 64
    assert ref.document_id == "doc_aaaaaaaa"
    assert ref.block_id == "block_bbbbbbbb"


# ─── 8. evidence_type preserved verbatim ────────────────────────────────


def test_evidence_type_preserved_verbatim():
    """evidence_type comes from the Evidence value object — the binder does
    NOT recompute it. Test every allowed value (spec §5.7 vocabulary)."""
    cv = _core_view(
        _evidence(evidence_id="ev_dtq", evidence_type="direct_quote"),
        _evidence(evidence_id="ev_ss", evidence_type="structured_source"),
        _evidence(evidence_id="ev_code", evidence_type="code"),
        _evidence(evidence_id="ev_comp", evidence_type="computed"),
        _evidence(evidence_id="ev_ms", evidence_type="multi_source"),
        _evidence(evidence_id="ev_inf", evidence_type="inferred"),
    )
    block = _block(
        evidence_refs=["ev_dtq", "ev_ss", "ev_code", "ev_comp", "ev_ms", "ev_inf"]
    )

    refs = bind_evidence(block, cv)
    got = {r.evidence_id: r.evidence_type for r in refs}

    assert got == {
        "ev_dtq": "direct_quote",
        "ev_ss": "structured_source",
        "ev_code": "code",
        "ev_comp": "computed",
        "ev_ms": "multi_source",
        "ev_inf": "inferred",
    }


# ─── 9. strength defaults to "medium" (B-T3a placeholder) ──────────────


def test_evidence_ref_strength_defaults_to_medium_for_all_refs():
    """B-T3a placeholder: EvidenceRef.strength = "medium" until StrengthPolicy
    integration in B-T3b. Verified across multiple refs to guarantee no
    per-id recomputation."""
    cv = _core_view(
        _evidence(evidence_id="ev_a", confidence=0.1),
        _evidence(evidence_id="ev_b", confidence=0.99),
        _evidence(evidence_id="ev_c", confidence=0.5),
    )
    block = _block(evidence_refs=["ev_a", "ev_b", "ev_c"])

    refs = bind_evidence(block, cv)

    assert all(r.strength == "medium" for r in refs), (
        "B-T3a sets strength='medium' for ALL refs; B-T3b will replace this "
        "with the real StrengthPolicy (see docstring of EvidenceRef)."
    )


# ─── 10. frozen dataclass ────────────────────────────────────────────────


def test_evidence_ref_is_frozen_cannot_be_mutated():
    """EvidenceRef is a frozen dataclass — mutating any field after
    construction raises ``dataclasses.FrozenInstanceError`` (a subclass of
    ``AttributeError``). This protects the snapshot semantics for downstream
    renders that hold the ref after core_view is gone."""
    cv = _core_view(_evidence(evidence_id="ev_freeze"))
    block = _block(evidence_refs=["ev_freeze"])

    refs = bind_evidence(block, cv)
    ref = refs[0]

    with pytest.raises(AttributeError):
        ref.evidence_id = "ev_hacked"  # type: ignore[misc]


# ─── 11. same evidence_id across two blocks → independent binds ────────


def test_same_evidence_id_in_two_blocks_yields_independent_evidence_refs():
    """Two blocks referencing the same evidence_id get independent
    EvidenceRef instances. (Both blocks see the same backing Evidence, but
    the dataclass snapshots they carry are distinct objects — sharing the
    underlying Evidence in core_view is allowed and expected.)"""
    shared_ev = _evidence(evidence_id="ev_shared", quote="shared content")
    cv = _core_view(shared_ev)
    block_a = _block(evidence_refs=["ev_shared"])
    block_b = _block(evidence_refs=["ev_shared"])

    refs_a = bind_evidence(block_a, cv)
    refs_b = bind_evidence(block_b, cv)

    # Both binds succeeded with the same content
    assert len(refs_a) == 1 and len(refs_b) == 1
    assert refs_a[0].evidence_id == refs_b[0].evidence_id == "ev_shared"

    # Independent instances — modifying one (or passing to different
    # downstream consumers) must not affect the other.
    assert refs_a[0] is not refs_b[0]


# ─── 12. empty core_view + non-empty block.evidence_refs → ValueError ───


def test_empty_core_view_with_non_empty_block_raises_value_error():
    """Empty core_view cannot satisfy any non-empty block.evidence_refs —
    even a single missing ID raises ValueError."""
    cv = SimpleKnowledgeCoreView()  # everything empty
    block = _block(evidence_refs=["ev_anything"])

    with pytest.raises(ValueError) as excinfo:
        bind_evidence(block, cv)

    assert "ev_anything" in str(excinfo.value)
