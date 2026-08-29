"""Tests for Book diff and affected chapter analysis (Task 2, A8)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.kc.views.book import Book, Chapter, BookDiff, affected_chapters, compute_book_diff


def _book(*, chapter_ids: list[str]) -> Book:
    return Book(id="book_12345678_diff", title="Diff", template_id="tpl", chapter_ids=chapter_ids)


def _chapter(
    *,
    id: str,
    title: str,
    order: int,
    source_knowledge_unit_ids: list[str],
    knowledge_block_ids: list[str] | None = None,
    publication_version: int = 1,
    stable_key: str | None = None,
) -> Chapter:
    return Chapter(
        id=id,
        book_id="book_12345678_diff",
        stable_key=stable_key or id,
        title=title,
        order=order,
        knowledge_block_ids=knowledge_block_ids or [],
        source_knowledge_unit_ids=source_knowledge_unit_ids,
        publication_version=publication_version,
    )


def test_compute_book_diff_detects_added_removed_changed_chapters_and_ku_delta() -> None:
    old = _book(chapter_ids=["ch_a", "ch_b", "ch_c"])
    new = _book(chapter_ids=["ch_c", "ch_b", "ch_d"])

    old_chapters = (
        _chapter(id="ch_a", title="A", order=1, source_knowledge_unit_ids=["ku_a"]),
        _chapter(
            id="ch_b",
            title="B",
            order=2,
            source_knowledge_unit_ids=["ku_shared", "ku_b_old"],
        ),
        _chapter(
            id="ch_c",
            title="C",
            order=3,
            source_knowledge_unit_ids=["ku_c"],
        ),
    )
    new_chapters = (
        _chapter(
            id="ch_c",
            title="C revised",
            order=1,
            source_knowledge_unit_ids=["ku_c"],
            publication_version=2,
        ),
        _chapter(
            id="ch_b",
            title="B",
            order=2,
            source_knowledge_unit_ids=["ku_shared", "ku_b_new"],
        ),
        _chapter(id="ch_d", title="D", order=3, source_knowledge_unit_ids=["ku_d"]),
    )

    diff = compute_book_diff(old, new, old_chapters=old_chapters, new_chapters=new_chapters)

    assert diff.added_chapter_ids == ("ch_d",)
    assert diff.removed_chapter_ids == ("ch_a",)
    assert diff.changed_chapter_ids == ("ch_c", "ch_b")
    assert diff.changed_knowledge_unit_ids == ("ku_a", "ku_b_old", "ku_b_new", "ku_d")


def test_compute_book_diff_only_reports_ku_changes_when_source_ids_change() -> None:
    old = _book(chapter_ids=["ch_a"])
    new = _book(chapter_ids=["ch_a"])

    old_chapters = (
        _chapter(
            id="ch_a",
            title="A",
            order=1,
            source_knowledge_unit_ids=["ku_a", "ku_shared"],
            publication_version=1,
        ),
    )
    new_chapters = (
        _chapter(
            id="ch_a",
            title="A revised",
            order=2,
            source_knowledge_unit_ids=["ku_a", "ku_shared"],
            publication_version=9,
        ),
    )

    diff = compute_book_diff(old, new, old_chapters=old_chapters, new_chapters=new_chapters)

    assert diff.added_chapter_ids == ()
    assert diff.removed_chapter_ids == ()
    assert diff.changed_chapter_ids == ("ch_a",)
    assert diff.changed_knowledge_unit_ids == ()


def test_compute_book_diff_uses_book_ids_when_chapters_are_not_provided() -> None:
    old = _book(chapter_ids=["ch_a", "ch_b"])
    new = _book(chapter_ids=["ch_b", "ch_a"])

    diff = compute_book_diff(old, new)

    assert diff.added_chapter_ids == ()
    assert diff.removed_chapter_ids == ()
    assert diff.changed_chapter_ids == ("ch_b", "ch_a")
    assert diff.changed_knowledge_unit_ids == ()


def test_compute_book_diff_detects_knowledge_block_id_changes() -> None:
    old = _book(chapter_ids=["ch_a"])
    new = _book(chapter_ids=["ch_a"])

    old_chapters = (
        _chapter(
            id="ch_a",
            title="A",
            order=1,
            knowledge_block_ids=["kb_1", "kb_2"],
            source_knowledge_unit_ids=["ku_a"],
        ),
    )
    new_chapters = (
        _chapter(
            id="ch_a",
            title="A",
            order=1,
            knowledge_block_ids=["kb_1", "kb_3"],
            source_knowledge_unit_ids=["ku_a"],
        ),
    )

    diff = compute_book_diff(old, new, old_chapters=old_chapters, new_chapters=new_chapters)

    assert diff.added_chapter_ids == ()
    assert diff.removed_chapter_ids == ()
    assert diff.changed_chapter_ids == ("ch_a",)
    assert diff.changed_knowledge_unit_ids == ()


def test_affected_chapters_dedupes_kus_and_preserves_chapter_order() -> None:
    chapters = (
        _chapter(id="ch_b", title="B", order=1, source_knowledge_unit_ids=["ku_x"]),
        _chapter(
            id="ch_c",
            title="C",
            order=2,
            source_knowledge_unit_ids=["ku_shared", "ku_y"],
        ),
        _chapter(id="ch_d", title="D", order=3, source_knowledge_unit_ids=["ku_z"]),
    )

    result = affected_chapters(
        chapters,
        ("ku_y", "ku_x", "ku_y", "ku_missing", "ku_x", "ku_shared"),
    )

    assert result == ("ch_b", "ch_c")


def test_affected_chapters_returns_empty_for_unrelated_kus() -> None:
    chapters = (
        _chapter(id="ch_b", title="B", order=1, source_knowledge_unit_ids=["ku_x"]),
        _chapter(id="ch_c", title="C", order=2, source_knowledge_unit_ids=["ku_y"]),
    )

    assert affected_chapters(chapters, ("ku_missing", "ku_other")) == ()


def test_book_diff_is_frozen_and_exposed_from_package() -> None:
    diff = BookDiff(
        added_chapter_ids=("ch_d",),
        removed_chapter_ids=("ch_a",),
        changed_chapter_ids=("ch_b",),
        changed_knowledge_unit_ids=("ku_b",),
    )

    assert diff.added_chapter_ids == ("ch_d",)
    with pytest.raises(FrozenInstanceError):
        diff.added_chapter_ids = ("ch_x",)  # type: ignore[misc]
