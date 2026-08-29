"""Tests for SimpleKnowledgeCoreView (B-T3a, spec §12.5 + §14 A8 step 1244).

Coverage (B-T3a scope — Protocol + in-memory default impl):

    1.  default construction: all dicts empty, version = 0
    2.  get_ku found → KU, not found → None
    3.  get_evidence found → Evidence, not found → None
    4.  get_claim found → value, not found → None
    5.  current_publication_version returns the stored value
    6.  kus_for_chapter with 3 KU ids → returns them in order
    7.  kus_for_chapter missing KU id → ValueError naming the missing id
    8.  kus_for_chapter empty source_knowledge_unit_ids → empty tuple
    9.  KnowledgeCoreView Protocol: SimpleKnowledgeCoreView structurally
        satisfies the Protocol (verified by static inspection — the Protocol
        is intentionally NOT runtime_checkable; see module docstring)

NO compiler, IntegrityGate, retrieval, or JSONL tests — those live later.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

# Imports intentionally fail before implementation — TDD red phase.
from src.kc.contracts.evidence import Evidence
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book import Chapter
from src.kc.views.book.core_view import (
    KnowledgeCoreView,
    SimpleKnowledgeCoreView,
)


# ─── Helpers ─────────────────────────────────────────────────────────────


def _ku(
    *,
    ku_id: str = "ku_default000_def",
    concept_id: str = "concept_default_intent",
    title: str = "default KU",
    unit_type: str = "definition",
) -> KnowledgeUnit:
    """Build a minimal KU carrying only the fields ``core_view`` needs."""
    return KnowledgeUnit(
        ku_id=ku_id,
        concept_id=concept_id,
        question="q",
        title=title,
        unit_type=unit_type,  # type: ignore[arg-type]
    )


def _evidence(evidence_id: str = "ev_default000_x") -> Evidence:
    return Evidence(evidence_id=evidence_id, quote="q", quote_hash="h")


@dataclass
class _StubClaim:
    """Duck-typed Claim — KnowledgeCoreView.get_claim returns Any to avoid
    coupling to claim implementation choices."""

    claim_id: str


# ─── 1. default construction ────────────────────────────────────────────


def test_default_construction_all_dicts_empty_version_zero():
    """A default-constructed view has empty dicts for kus/evidences/claims
    and a publication_version of 0."""
    cv = SimpleKnowledgeCoreView()

    assert cv.kus == {}
    assert cv.evidences == {}
    assert cv.claims == {}
    assert cv.publication_version == 0


# ─── 2. get_ku found / not-found ────────────────────────────────────────


def test_get_ku_returns_ku_when_present_none_when_absent():
    """get_ku returns the KU when the id is registered, else None."""
    ku = _ku(ku_id="ku_present001_abc")
    cv = SimpleKnowledgeCoreView(kus={"ku_present001_abc": ku})

    assert cv.get_ku("ku_present001_abc") is ku
    assert cv.get_ku("ku_absent001_xyz") is None


# ─── 3. get_evidence found / not-found ──────────────────────────────────


def test_get_evidence_returns_evidence_when_present_none_when_absent():
    """get_evidence returns the Evidence when the id is registered, else None."""
    ev = _evidence("ev_present001_abc")
    cv = SimpleKnowledgeCoreView(evidences={"ev_present001_abc": ev})

    assert cv.get_evidence("ev_present001_abc") is ev
    assert cv.get_evidence("ev_absent001_xyz") is None


# ─── 4. get_claim found / not-found ─────────────────────────────────────


def test_get_claim_returns_value_when_present_none_when_absent():
    """get_claim accepts Any duck-typed claim object. Return None on miss."""
    claim = _StubClaim(claim_id="claim_present001_abc")
    cv = SimpleKnowledgeCoreView(claims={"claim_present001_abc": claim})

    assert cv.get_claim("claim_present001_abc") is claim
    assert cv.get_claim("claim_absent001_xyz") is None


# ─── 5. current_publication_version ─────────────────────────────────────


def test_current_publication_version_returns_stored_value():
    """Book views MUST read this rather than invent their own version
    counter (spec §17 D-21). Defaults to 0; the stored value is returned
    verbatim."""
    cv_default = SimpleKnowledgeCoreView()
    assert cv_default.current_publication_version() == 0

    cv_v7 = SimpleKnowledgeCoreView(publication_version=7)
    assert cv_v7.current_publication_version() == 7


# ─── 6. kus_for_chapter with multiple KU ids in order ──────────────────


def test_kus_for_chapter_returns_kus_in_order():
    """``kus_for_chapter`` batch-fetches KUs in the order they appear in
    ``chapter.source_knowledge_unit_ids`` (NOT dict insertion order)."""
    ku1 = _ku(ku_id="ku_order001_aaa")
    ku2 = _ku(ku_id="ku_order002_bbb")
    ku3 = _ku(ku_id="ku_order003_ccc")
    cv = SimpleKnowledgeCoreView(
        kus={
            "ku_order001_aaa": ku1,
            "ku_order002_bbb": ku2,
            "ku_order003_ccc": ku3,
        }
    )
    chapter = Chapter(
        id="ch_11111111_x",
        book_id="book_00000000_y",
        stable_key="concept_x::definition",
        title="x",
        order=1,
        source_knowledge_unit_ids=["ku_order003_ccc", "ku_order001_aaa", "ku_order002_bbb"],
    )

    result = cv.kus_for_chapter(chapter)

    assert isinstance(result, tuple)
    assert list(result) == [ku3, ku1, ku2]


# ─── 7. kus_for_chapter missing KU → ValueError ────────────────────────


def test_kus_for_chapter_raises_value_error_when_ku_id_missing():
    """Missing KU id in ``chapter.source_knowledge_unit_ids`` is a
    programmer error (B-T3 strict); the missing id appears in the error."""
    cv = SimpleKnowledgeCoreView(kus={})
    chapter = Chapter(
        id="ch_11111111_x",
        book_id="book_00000000_y",
        stable_key="concept_x::definition",
        title="x",
        order=1,
        source_knowledge_unit_ids=["ku_missing001_xyz"],
    )

    with pytest.raises(ValueError) as excinfo:
        cv.kus_for_chapter(chapter)

    assert "ku_missing001_xyz" in str(excinfo.value)


# ─── 8. kus_for_chapter with empty source_knowledge_unit_ids ────────────


def test_kus_for_chapter_empty_source_returns_empty_tuple():
    """A chapter with no source KUs (e.g. a placeholder chapter) yields an
    empty tuple — not an error."""
    cv = SimpleKnowledgeCoreView(kus={})
    chapter = Chapter(
        id="ch_11111111_x",
        book_id="book_00000000_y",
        stable_key="concept_x::definition",
        title="x",
        order=1,
        source_knowledge_unit_ids=[],
    )

    assert cv.kus_for_chapter(chapter) == ()


# ─── 9. KnowledgeCoreView Protocol surface ───────────────────────────────


def test_simple_knowledge_core_view_implements_the_protocol():
    """SimpleKnowledgeCoreView must satisfy the KnowledgeCoreView Protocol.

    KnowledgeCoreView is intentionally NOT @runtime_checkable (see the
    Protocol's module docstring); this test verifies the surface statically
    by checking that every Protocol method is present with the correct
    signature intent.
    """
    cv = SimpleKnowledgeCoreView()

    # All five Protocol methods must exist and be callable.
    assert callable(getattr(cv, "get_ku", None))
    assert callable(getattr(cv, "get_evidence", None))
    assert callable(getattr(cv, "get_claim", None))
    assert callable(getattr(cv, "current_publication_version", None))
    assert callable(getattr(cv, "kus_for_chapter", None))

    # KnowledgeCoreView itself is a Protocol (a typing construct).
    assert KnowledgeCoreView is not None
