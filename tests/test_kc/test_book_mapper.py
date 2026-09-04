"""Tests for the KU → Chapter mapper (B-T2, spec §12.5 + §14 A8 step 1243).

Two layers:

A) Pure unit tests (~ 17 tests): build ``KnowledgeUnit`` and
   ``BookChapterRegistry`` instances in code, assert the mapping decisions.
   Cover every reason code at least 3 times and exercise edge cases
   (empty registry, multiple candidate chapters, missing fields).

B) Gold standard tests (~ 5 tests): parametrize the ≥ 30 cases from
   ``tests/fixtures/book_mapping.yaml``. Each case asserts the 4-tuple
   ``(chapter_id, stable_key, confidence, reason)``. The accuracy score
   must satisfy ``accuracy >= 0.90`` (Gate A8 spec).

TDD scope (B-T2 — mapper layer only):
  * No compiler, no binder, no outline engine — those land in B-T3+.
  * Mapper is pure: no I/O, no mutation, no logging side-effects.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Imports intentionally fail before implementation — TDD red phase.
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book import Chapter
from src.kc.views.book.mapper import (
    BookChapterRegistry,
    MappingDecision,
    MappingHint,
    derive_stable_key,
    map_ku_to_chapter,
)


# ─── Helpers ────────────────────────────────────────────────────────────


def _ku(
    *,
    ku_id: str = "ku_a1b2c3d4_def",
    concept_id: str = "concept_e5f6g7h8_intent",
    question: str = "What is the canonical intent?",
    title: str = "Canonical intent definition",
    unit_type: str = "definition",
    knowledge_mode: str = "observed",
    context_id: str | None = None,
    validity_id: str | None = None,
) -> KnowledgeUnit:
    """Build a fully populated KnowledgeUnit (only the fields the mapper reads
    matter for the B-T2 surface; the rest use sensible defaults so the test
    surface stays compact).
    """
    return KnowledgeUnit(
        ku_id=ku_id,
        concept_id=concept_id,
        question=question,
        title=title,
        unit_type=unit_type,  # type: ignore[arg-type]
        knowledge_mode=knowledge_mode,  # type: ignore[arg-type]
        context_id=context_id,
        validity_id=validity_id,
    )


def _chapter(
    *,
    id: str = "ch_11111111_alpha",
    book_id: str = "book_00000000_x",
    stable_key: str = "concept_e5f6g7h8_intent::definition",
    title: str = "Intent definitions",
    order: int = 1,
    source_knowledge_unit_ids: tuple[str, ...] = (),
) -> Chapter:
    """Build a Chapter with the minimal surface the mapper inspects."""
    return Chapter(
        id=id,
        book_id=book_id,
        stable_key=stable_key,
        title=title,
        order=order,
        source_knowledge_unit_ids=list(source_knowledge_unit_ids),
    )


def _registry(*chapters: Chapter) -> BookChapterRegistry:
    """Convenience wrapper to build a registry from varargs."""
    return BookChapterRegistry(chapters=tuple(chapters))


# ─── Test A1: derive_stable_key contract ───────────────────────────────


def test_derive_stable_key_concatenates_concept_and_unit_type():
    """derive_stable_key joins concept_id and unit_type with '::' separator.

    Per task spec §4 + B-T2 mapping rules — this is the canonical derivation
    callers use when CREATING new chapters from a KU.
    """
    ku = _ku(concept_id="concept_abc_def", unit_type="principle")
    assert derive_stable_key(ku) == "concept_abc_def::principle"


def test_derive_stable_key_changes_when_unit_type_changes():
    """The same concept paired with a different unit_type yields a different
    stable_key — so 'concept X definition' and 'concept X mechanism' get
    distinct chapters (per §9 / A3 concept+unit_type derivation).
    """
    base_concept = "concept_z9_diff"
    key_def = derive_stable_key(_ku(concept_id=base_concept, unit_type="definition"))
    key_mech = derive_stable_key(_ku(concept_id=base_concept, unit_type="mechanism"))
    assert key_def != key_mech
    assert key_def == f"{base_concept}::definition"
    assert key_mech == f"{base_concept}::mechanism"


# ─── Test A2: Registry finders (sanity checks for the surface) ─────────


def test_registry_find_by_stable_key_returns_matching_chapter():
    ch = _chapter(stable_key="concept_alpha::method")
    reg = _registry(ch)
    assert reg.find_by_stable_key("concept_alpha::method") is ch


def test_registry_find_by_stable_key_returns_none_when_missing():
    reg = _registry(_chapter(stable_key="concept_alpha::method"))
    assert reg.find_by_stable_key("concept_beta::method") is None


def test_registry_find_by_ku_id_returns_matching_chapter():
    ch = _chapter(source_knowledge_unit_ids=("ku_aaa", "ku_bbb"))
    reg = _registry(ch)
    assert reg.find_by_ku_id("ku_bbb") is ch


def test_registry_find_by_ku_id_returns_none_when_missing():
    reg = _registry(_chapter(source_knowledge_unit_ids=("ku_aaa",)))
    assert reg.find_by_ku_id("ku_zzz") is None


def test_registry_empty_find_returns_none():
    """Empty registry: every find returns None (edge case for early boot)."""
    reg = _registry()
    assert reg.find_by_stable_key("anything") is None
    assert reg.find_by_ku_id("ku_anything") is None
    assert reg.find_by_concept_id("concept_anything") is None


# ─── Test A3: exact_ku_match ───────────────────────────────────────────


def test_exact_ku_match_when_ku_id_is_in_source_knowledge_unit_ids():
    """Reason code 'exact_ku_match' (confidence 1.0) wins over every other
    signal when the KU is already a source of the chapter.
    """
    target = _chapter(
        id="ch_match_target",
        stable_key="concept_x::definition",
        source_knowledge_unit_ids=("ku_target_001", "ku_other"),
    )
    other = _chapter(
        id="ch_collision",
        stable_key="concept_x::definition",  # same stable_key as target
        source_knowledge_unit_ids=("ku_different",),
    )
    reg = _registry(target, other)

    ku = _ku(ku_id="ku_target_001", concept_id="concept_x", unit_type="definition")
    decision = map_ku_to_chapter(ku, reg)

    assert decision.chapter_id == "ch_match_target"
    assert decision.reason == "exact_ku_match"
    assert decision.confidence == 1.0


# ─── Test A4: exact_stable_key ──────────────────────────────────────────


def test_exact_stable_key_via_mapping_hint_wins_over_derivation():
    """When a MappingHint(stable_key=...) is provided AND a chapter carries
    that exact stable_key, that chapter wins at confidence 0.95.
    """
    target = _chapter(
        id="ch_hint_target",
        stable_key="concept_alpha::method",
        source_knowledge_unit_ids=(),
    )
    derivation = _chapter(
        id="ch_derivation_collision",
        stable_key="concept_alpha::principle",
        source_knowledge_unit_ids=(),
    )
    reg = _registry(target, derivation)

    # KU's own concept+unit_type derivation would land on derivation,
    # but the explicit hint must win.
    ku = _ku(concept_id="concept_alpha", unit_type="principle")
    hint = MappingHint(stable_key="concept_alpha::method")
    decision = map_ku_to_chapter(ku, reg, hint=hint)

    assert decision.chapter_id == "ch_hint_target"
    assert decision.reason == "exact_stable_key"
    assert decision.confidence == 0.95


def test_exact_stable_key_hint_falls_through_when_no_match():
    """If the hinted stable_key is not present in the registry, fall through
    to the next available signal (concept+unit_type derivation in this test).
    """
    target = _chapter(
        id="ch_derived",
        stable_key="concept_x::principle",
        source_knowledge_unit_ids=(),
    )
    reg = _registry(target)

    ku = _ku(concept_id="concept_x", unit_type="principle")
    hint = MappingHint(stable_key="concept_nonexistent::pattern")
    decision = map_ku_to_chapter(ku, reg, hint=hint)

    assert decision.chapter_id == "ch_derived"
    assert decision.reason == "concept_unit_type_match"
    assert decision.confidence == 0.85


# ─── Test A5: concept_unit_type_match ──────────────────────────────────


def test_concept_unit_type_derivation_matches_existing_chapter():
    """When no exact KU match and no hint, derive ``concept::unit_type`` and
    search by it. reason='concept_unit_type_match', confidence=0.85.
    """
    ch = _chapter(
        id="ch_derived",
        stable_key="concept_y::case",
        source_knowledge_unit_ids=(),
    )
    reg = _registry(ch)

    ku = _ku(concept_id="concept_y", unit_type="case", ku_id="ku_fresh")
    decision = map_ku_to_chapter(ku, reg)

    assert decision.chapter_id == "ch_derived"
    assert decision.reason == "concept_unit_type_match"
    assert decision.confidence == 0.85
    assert decision.stable_key == "concept_y::case"


# ─── Test A6: needs_new_chapter ─────────────────────────────────────────


def test_needs_new_chapter_when_no_signal_matches():
    """Empty registry → needs_new_chapter, chapter_id=None."""
    reg = _registry()
    ku = _ku(concept_id="concept_orphan", unit_type="event")
    decision = map_ku_to_chapter(ku, reg)
    assert decision.chapter_id is None
    assert decision.reason == "needs_new_chapter"
    assert decision.confidence == 0.0
    # The decision still surfaces the derived stable_key so the caller
    # can create a new chapter using the canonical derivation.
    assert decision.stable_key == "concept_orphan::event"


def test_needs_new_chapter_when_only_other_concept_present():
    """Registry has a chapter for a different concept — caller must create."""
    reg = _registry(
        _chapter(id="ch_other", stable_key="concept_x::definition"),
    )
    ku = _ku(concept_id="concept_y", unit_type="definition")
    decision = map_ku_to_chapter(ku, reg)
    assert decision.chapter_id is None
    assert decision.reason == "needs_new_chapter"
    assert decision.stable_key == "concept_y::definition"


# ─── Test A7: edge cases ───────────────────────────────────────────────


def test_exact_ku_match_beats_hint():
    """If both exact_ku_match AND exact_stable_key hint apply, exact_ku_match
    wins (it's higher confidence and comes first in the resolution order).
    """
    hinted = _chapter(
        id="ch_hinted",
        stable_key="concept_z::pattern",
        source_knowledge_unit_ids=(),
    )
    exact = _chapter(
        id="ch_exact",
        stable_key="concept_z::pattern",  # same stable_key as hinted
        source_knowledge_unit_ids=("ku_kk",),
    )
    reg = _registry(hinted, exact)

    ku = _ku(ku_id="ku_kk", concept_id="concept_z", unit_type="pattern")
    hint = MappingHint(stable_key="concept_z::pattern")
    decision = map_ku_to_chapter(ku, reg, hint=hint)

    assert decision.chapter_id == "ch_exact"
    assert decision.reason == "exact_ku_match"


def test_first_match_wins_when_multiple_chapters_share_stable_key():
    """Determinism: when two chapters share the same stable_key, the mapper
    must pick deterministically (first occurrence in registry order).
    """
    first = _chapter(id="ch_first", stable_key="concept_q::process")
    second = _chapter(id="ch_second", stable_key="concept_q::process")
    reg = _registry(first, second)

    ku = _ku(concept_id="concept_q", unit_type="process")
    decision = map_ku_to_chapter(ku, reg)
    assert decision.chapter_id == "ch_first"


def test_mapping_decision_is_frozen_dataclass_with_required_fields():
    """MappingDecision is a frozen dataclass with 4 required fields."""
    md = MappingDecision(
        chapter_id="ch_x",
        stable_key="concept_x::definition",
        confidence=0.85,
        reason="concept_unit_type_match",
    )
    assert md.chapter_id == "ch_x"
    assert md.stable_key == "concept_x::definition"
    assert md.confidence == 0.85
    assert md.reason == "concept_unit_type_match"
    # Frozen: assignment must raise.
    with pytest.raises((AttributeError, Exception)):
        md.chapter_id = "ch_y"  # type: ignore[misc]


def test_decision_supports_needs_new_with_none_chapter_id():
    """MappingDecision with chapter_id=None represents 'needs_new_chapter'."""
    md = MappingDecision(
        chapter_id=None,
        stable_key="concept_new::method",
        confidence=0.0,
        reason="needs_new_chapter",
    )
    assert md.chapter_id is None
    assert md.reason == "needs_new_chapter"


# ─── Test A8: ensure all 4 reason codes are exercised ≥ 3 times ────────


@pytest.mark.parametrize(
    "reason_code",
    [
        "exact_ku_match",
        "exact_stable_key",
        "concept_unit_type_match",
        "needs_new_chapter",
    ],
)
def test_each_reason_code_reachable_with_minimal_inputs(reason_code):
    """Smoke check: every documented reason code is reachable. Detailed
    semantic coverage lives in the gold standard YAML; this test simply
    guards against silent code removal (e.g. someone deletes the hint path).
    """
    if reason_code == "exact_ku_match":
        ch = _chapter(
            id="ch_ex",
            stable_key="concept_a::definition",
            source_knowledge_unit_ids=("ku_match",),
        )
        reg = _registry(ch)
        ku = _ku(ku_id="ku_match", concept_id="concept_a", unit_type="definition")
        decision = map_ku_to_chapter(ku, reg)
    elif reason_code == "exact_stable_key":
        ch = _chapter(
            id="ch_hint", stable_key="concept_b::principle", source_knowledge_unit_ids=()
        )
        reg = _registry(ch)
        ku = _ku(concept_id="concept_b", unit_type="principle")
        decision = map_ku_to_chapter(ku, reg, hint=MappingHint(stable_key="concept_b::principle"))
    elif reason_code == "concept_unit_type_match":
        ch = _chapter(
            id="ch_der", stable_key="concept_c::case", source_knowledge_unit_ids=()
        )
        reg = _registry(ch)
        ku = _ku(concept_id="concept_c", unit_type="case")
        decision = map_ku_to_chapter(ku, reg)
    else:  # needs_new_chapter
        reg = _registry()
        ku = _ku(concept_id="concept_d", unit_type="event")
        decision = map_ku_to_chapter(ku, reg)
    assert decision.reason == reason_code


# ─── Test B: gold standard (parametrized from YAML) ─────────────────────


_GOLD_PATH = Path("tests/fixtures/book_mapping.yaml")


def _load_gold_cases() -> list[dict[str, Any]]:
    """Load the B-T2 gold standard YAML as the single source of truth."""
    assert _GOLD_PATH.exists(), (
        f"Gold standard fixture missing: {_GOLD_PATH}. "
        "B-T2 cannot validate mapper accuracy without it."
    )
    cases = yaml.safe_load(_GOLD_PATH.read_text(encoding="utf-8"))
    assert isinstance(cases, list), "Gold standard must be a list of cases"
    assert len(cases) >= 30, (
        f"Gold standard must have >= 30 cases (got {len(cases)}); "
        "see B-T2 task spec distribution rules."
    )
    return cases


def _build_chapter_from_case(spec: dict[str, Any]) -> Chapter:
    """Build a Chapter from a YAML case's existing_chapters entry."""
    return Chapter(
        id=spec["chapter_id"],
        book_id="book_gold_00000000_root",
        stable_key=spec["stable_key"],
        title=spec.get("title", spec["stable_key"]),
        order=spec.get("order", 1),
        source_knowledge_unit_ids=list(spec.get("source_knowledge_unit_ids", ())),
    )


@pytest.fixture(scope="module")
def gold_cases() -> list[dict[str, Any]]:
    return _load_gold_cases()


def _run_gold_case(case: dict[str, Any]) -> tuple[MappingDecision, dict[str, Any]]:
    """Run one gold case through the mapper and return (decision, expected)."""
    ku_spec = case["ku"]
    ku = _ku(
        ku_id=ku_spec["id"],
        concept_id=ku_spec["concept_id"],
        unit_type=ku_spec["unit_type"],
        question=ku_spec.get("question", "What?"),
        title=ku_spec.get("title", "Title"),
    )
    chapters = tuple(
        _build_chapter_from_case(ch) for ch in case.get("existing_chapters", [])
    )
    reg = _registry(*chapters)
    hint = None
    if case.get("hint_stable_key"):
        hint = MappingHint(stable_key=case["hint_stable_key"])
    decision = map_ku_to_chapter(ku, reg, hint=hint)
    return decision, case["expected"]


def test_gold_dataset_has_at_least_30_cases(gold_cases: list[dict[str, Any]]):
    """Sanity: the dataset is large enough to evaluate."""
    assert len(gold_cases) >= 30


def test_gold_distribution_matches_required_categories(gold_cases: list[dict[str, Any]]):
    """The B-T2 spec requires a fixed distribution of reason codes. This
    guards against the YAML drifting away from the spec."""
    counts: dict[str, int] = {
        "exact_ku_match": 0,
        "exact_stable_key": 0,
        "concept_unit_type_match": 0,
        "needs_new_chapter": 0,
    }
    for case in gold_cases:
        reason = case["expected"]["reason"]
        counts[reason] = counts.get(reason, 0) + 1
    assert counts["exact_ku_match"] >= 6, counts
    assert counts["exact_stable_key"] >= 4, counts
    assert counts["concept_unit_type_match"] >= 6, counts
    assert counts["needs_new_chapter"] >= 4, counts


def test_gold_case_run(gold_cases: list[dict[str, Any]]):
    """Run every gold case individually; per-case assertion lives in the
    parametrized test below. This test simply prints accuracy and asserts
    the Gate A8 threshold of 0.90.
    """
    matched = 0
    total = len(gold_cases)
    for case in gold_cases:
        decision, expected = _run_gold_case(case)
        if (
            decision.chapter_id == expected.get("chapter_id")
            and decision.stable_key == expected["stable_key"]
            and decision.confidence == pytest.approx(expected["confidence"])
            and decision.reason == expected["reason"]
        ):
            matched += 1

    accuracy = matched / total
    # Print for human review; pytest -v captures this.
    print(f"\nB-T2 gold standard accuracy: {matched}/{total} = {accuracy:.4f}")
    assert accuracy >= 0.90, (
        f"Gate A8 requires accuracy >= 0.90, got {accuracy:.4f} "
        f"({matched}/{total})"
    )


@pytest.mark.parametrize("case", _load_gold_cases(), ids=lambda c: c["case_id"])
def test_gold_case_each(case: dict[str, Any]):
    """Per-case 4-tuple assertion. Failure here pinpoints which case drifted."""
    decision, expected = _run_gold_case(case)
    assert decision.chapter_id == expected.get("chapter_id"), (
        f"chapter_id mismatch in {case['case_id']}: "
        f"got {decision.chapter_id!r}, expected {expected.get('chapter_id')!r}"
    )
    assert decision.stable_key == expected["stable_key"], (
        f"stable_key mismatch in {case['case_id']}: "
        f"got {decision.stable_key!r}, expected {expected['stable_key']!r}"
    )
    assert decision.confidence == pytest.approx(expected["confidence"]), (
        f"confidence mismatch in {case['case_id']}: "
        f"got {decision.confidence}, expected {expected['confidence']}"
    )
    assert decision.reason == expected["reason"], (
        f"reason mismatch in {case['case_id']}: "
        f"got {decision.reason!r}, expected {expected['reason']!r}"
    )
