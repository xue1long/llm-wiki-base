"""Outline proposal engine for Book views (Task 1, A8).

This module turns the frozen ``OutlineProposal`` contract into a tiny
public API:

* create a validated proposal from a Book
* approve a proposed proposal
* apply an approved proposal to produce a new Book/version

The implementation stays intentionally small: copy inputs, dedupe ordered
tuples, validate the mapping pair, and never mutate caller-owned objects.
"""
from __future__ import annotations

from src.kc.views.book.contract import (
    Book,
    OutlineProposal,
    OutlineProposalStatus,
)
from src.kc.views.book.id_policy import generate_outline_proposal_id


def _dedupe_preserve_order(items: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _validate_mapping_pair(
    migration_mapping: dict[str, str],
    rollback_mapping: dict[str, str],
) -> None:
    if len(migration_mapping) != len(rollback_mapping):
        raise ValueError("OutlineProposal mappings must be complete and symmetric")

    for stable_key, new_chapter_id in migration_mapping.items():
        if not stable_key or not new_chapter_id:
            raise ValueError("OutlineProposal mappings must not contain empty ids")
        if rollback_mapping.get(new_chapter_id) != stable_key:
            raise ValueError("OutlineProposal rollback mapping must invert migration mapping")

    for new_chapter_id, stable_key in rollback_mapping.items():
        if not new_chapter_id or not stable_key:
            raise ValueError("OutlineProposal mappings must not contain empty ids")
        if migration_mapping.get(stable_key) != new_chapter_id:
            raise ValueError("OutlineProposal migration mapping must invert rollback mapping")


def create_outline_proposal(
    book: Book,
    *,
    trigger_knowledge_unit_ids: tuple[str, ...],
    affected_chapter_ids: tuple[str, ...],
    migration_mapping: dict[str, str],
    rollback_mapping: dict[str, str],
) -> OutlineProposal:
    if not trigger_knowledge_unit_ids:
        raise ValueError("OutlineProposal requires at least one trigger knowledge unit")

    triggers = _dedupe_preserve_order(trigger_knowledge_unit_ids)
    affected = _dedupe_preserve_order(affected_chapter_ids)

    missing = [chapter_id for chapter_id in affected if chapter_id not in book.chapter_ids]
    if missing:
        raise ValueError(f"OutlineProposal affected chapters not in Book: {missing}")

    copied_migration = dict(migration_mapping)
    copied_rollback = dict(rollback_mapping)
    migration_targets = set(copied_migration.values())
    missing_coverage = [chapter_id for chapter_id in affected if chapter_id not in migration_targets]
    if missing_coverage:
        raise ValueError(
            "OutlineProposal affected chapters must be covered by migration mapping values"
        )
    _validate_mapping_pair(copied_migration, copied_rollback)

    return OutlineProposal(
        id=generate_outline_proposal_id(book.title or "outline"),
        book_id=book.id,
        trigger_knowledge_unit_ids=triggers,
        affected_chapter_ids=affected,
        migration_mapping=copied_migration,
        rollback_mapping=copied_rollback,
        status=OutlineProposalStatus.PROPOSED,
        reviewer=None,
    )


def approve_outline_proposal(
    proposal: OutlineProposal,
    *,
    reviewer: str,
) -> OutlineProposal:
    if proposal.status != OutlineProposalStatus.PROPOSED:
        raise ValueError("Only proposed OutlineProposal objects can be approved")
    if not reviewer:
        raise ValueError("reviewer is required")

    return OutlineProposal(
        id=proposal.id,
        book_id=proposal.book_id,
        trigger_knowledge_unit_ids=list(proposal.trigger_knowledge_unit_ids),
        affected_chapter_ids=list(proposal.affected_chapter_ids),
        migration_mapping=dict(proposal.migration_mapping),
        rollback_mapping=dict(proposal.rollback_mapping),
        status=OutlineProposalStatus.APPROVED,
        reviewer=reviewer,
    )


def apply_outline_proposal(book: Book, proposal: OutlineProposal) -> tuple[Book, OutlineProposal]:
    if proposal.book_id != book.id:
        raise ValueError("OutlineProposal.book_id must match the target Book")
    if proposal.status != OutlineProposalStatus.APPROVED:
        raise ValueError("Only approved OutlineProposal objects can be applied")

    updated_book = Book(
        id=book.id,
        title=book.title,
        template_id=book.template_id,
        outline_version=book.outline_version + 1,
        publication_version=book.publication_version,
        chapter_ids=list(book.chapter_ids),
    )
    applied = OutlineProposal(
        id=proposal.id,
        book_id=proposal.book_id,
        trigger_knowledge_unit_ids=list(proposal.trigger_knowledge_unit_ids),
        affected_chapter_ids=list(proposal.affected_chapter_ids),
        migration_mapping=dict(proposal.migration_mapping),
        rollback_mapping=dict(proposal.rollback_mapping),
        status=OutlineProposalStatus.APPLIED,
        reviewer=proposal.reviewer,
    )
    return updated_book, applied


__all__ = [
    "approve_outline_proposal",
    "apply_outline_proposal",
    "create_outline_proposal",
]
