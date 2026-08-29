"""Tests for the Book outline proposal engine (Task 1, A8).

Seam under test:
    - ``src.kc.views.book`` public API re-export
    - ``create_outline_proposal``
    - ``approve_outline_proposal``
    - ``apply_outline_proposal``

The tests stay at the public boundary and only exercise the frozen Book /
OutlineProposal contract plus the proposal lifecycle rules from the brief.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.kc.views.book import (
    Book,
    OutlineProposal,
    OutlineProposalStatus,
    approve_outline_proposal,
    apply_outline_proposal,
    create_outline_proposal,
)


def _book() -> Book:
    return Book(
        id="book_12345678_outline",
        title="Outline",
        template_id="tpl-default",
        chapter_ids=["ch_1", "ch_2"],
    )


def _proposal_kwargs() -> dict[str, object]:
    return {
        "trigger_knowledge_unit_ids": ("ku_1", "ku_1", "ku_2"),
        "affected_chapter_ids": ("ch_1", "ch_2", "ch_2"),
        "migration_mapping": {
            "stable_a": "ch_1_new",
            "stable_b": "ch_2_new",
        },
        "rollback_mapping": {
            "ch_1_new": "stable_a",
            "ch_2_new": "stable_b",
        },
    }


def test_create_outline_proposal_dedupes_inputs_and_defaults_to_proposed():
    book = _book()
    migration_mapping = {
        "stable_a": "ch_1",
        "stable_b": "ch_2",
    }
    rollback_mapping = {
        "ch_1": "stable_a",
        "ch_2": "stable_b",
    }

    proposal = create_outline_proposal(
        book,
        trigger_knowledge_unit_ids=("ku_1", "ku_1", "ku_2"),
        affected_chapter_ids=("ch_1", "ch_2", "ch_2"),
        migration_mapping=migration_mapping,
        rollback_mapping=rollback_mapping,
    )

    assert proposal.book_id == book.id
    assert proposal.trigger_knowledge_unit_ids == ["ku_1", "ku_2"]
    assert proposal.affected_chapter_ids == ["ch_1", "ch_2"]
    assert proposal.migration_mapping == migration_mapping
    assert proposal.rollback_mapping == rollback_mapping
    assert proposal.migration_mapping is not migration_mapping
    assert proposal.rollback_mapping is not rollback_mapping
    assert proposal.status == OutlineProposalStatus.PROPOSED
    assert proposal.reviewer is None
    assert book.chapter_ids == ["ch_1", "ch_2"]


def test_create_outline_proposal_rejects_empty_triggers():
    book = _book()
    with pytest.raises(ValueError):
        create_outline_proposal(
            book,
            trigger_knowledge_unit_ids=(),
            affected_chapter_ids=("ch_1",),
            migration_mapping={"stable_a": "ch_1"},
            rollback_mapping={"ch_1": "stable_a"},
        )


def test_create_outline_proposal_rejects_unknown_affected_chapter():
    book = _book()
    with pytest.raises(ValueError):
        create_outline_proposal(
            book,
            trigger_knowledge_unit_ids=("ku_1",),
            affected_chapter_ids=("ch_1", "ch_3"),
            migration_mapping={
                "stable_a": "ch_1",
                "stable_b": "ch_2",
            },
            rollback_mapping={
                "ch_1": "stable_a",
                "ch_2": "stable_b",
            },
        )


def test_create_outline_proposal_rejects_incomplete_mappings():
    book = _book()
    with pytest.raises(ValueError):
        create_outline_proposal(
            book,
            trigger_knowledge_unit_ids=("ku_1",),
            affected_chapter_ids=("ch_1", "ch_2"),
            migration_mapping={
                "stable_a": "ch_1",
            },
            rollback_mapping={
                "ch_1": "stable_a",
                "ch_2": "stable_b",
            },
        )


def test_create_outline_proposal_rejects_affected_chapter_without_migration_coverage():
    book = _book()
    with pytest.raises(ValueError):
        create_outline_proposal(
            book,
            trigger_knowledge_unit_ids=("ku_1",),
            affected_chapter_ids=("ch_1", "ch_2"),
            migration_mapping={
                "stable_a": "ch_1",
                "stable_b": "ch_3",
            },
            rollback_mapping={
                "ch_1": "stable_a",
                "ch_3": "stable_b",
            },
        )


def test_approve_and_apply_outline_proposal_are_frozen_and_non_mutating():
    book = _book()
    proposal = create_outline_proposal(
        book,
        trigger_knowledge_unit_ids=("ku_1", "ku_2"),
        affected_chapter_ids=("ch_1", "ch_2"),
        migration_mapping={
            "stable_a": "ch_1",
            "stable_b": "ch_2",
        },
        rollback_mapping={
            "ch_1": "stable_a",
            "ch_2": "stable_b",
        },
    )

    approved = approve_outline_proposal(proposal, reviewer="reviewer-1")
    assert approved.status == OutlineProposalStatus.APPROVED
    assert approved.reviewer == "reviewer-1"
    assert proposal.status == OutlineProposalStatus.PROPOSED
    assert proposal.reviewer is None

    with pytest.raises(FrozenInstanceError):
        approved.status = "rejected"  # type: ignore[misc]

    updated_book, applied = apply_outline_proposal(book, approved)
    assert updated_book is not book
    assert applied is not approved
    assert updated_book.outline_version == book.outline_version + 1
    assert updated_book.chapter_ids == book.chapter_ids
    assert updated_book.chapter_ids is not book.chapter_ids
    assert applied.status == OutlineProposalStatus.APPLIED
    assert applied.reviewer == "reviewer-1"
    assert book.outline_version == 1
    assert book.chapter_ids == ["ch_1", "ch_2"]
    assert approved.status == OutlineProposalStatus.APPROVED


@pytest.mark.parametrize(
    "status",
    [OutlineProposalStatus.PROPOSED, OutlineProposalStatus.REJECTED, OutlineProposalStatus.APPLIED],
)
def test_apply_outline_proposal_rejects_non_approved_status(status):
    book = _book()
    proposal = OutlineProposal(
        id="op_12345678_outline",
        book_id=book.id,
        trigger_knowledge_unit_ids=["ku_1"],
        affected_chapter_ids=["ch_1"],
        migration_mapping={"stable_a": "ch_1"},
        rollback_mapping={"ch_1": "stable_a"},
        status=status,
        reviewer="reviewer-1",
    )

    with pytest.raises(ValueError):
        apply_outline_proposal(book, proposal)


def test_apply_outline_proposal_increments_outline_version_once():
    book = _book()
    proposal = approve_outline_proposal(
        create_outline_proposal(
            book,
            trigger_knowledge_unit_ids=("ku_1",),
            affected_chapter_ids=("ch_1",),
            migration_mapping={"stable_a": "ch_1"},
            rollback_mapping={"ch_1": "stable_a"},
        ),
        reviewer="reviewer-1",
    )

    updated_book, applied = apply_outline_proposal(book, proposal)
    assert updated_book.outline_version == 2
    assert book.outline_version == 1
    assert applied.status == OutlineProposalStatus.APPLIED

    with pytest.raises(ValueError):
        apply_outline_proposal(updated_book, applied)
