"""Book diff and affected chapter analysis for Book views (Task 2, A8)."""
from __future__ import annotations

from dataclasses import dataclass

from src.kc.views.book.contract import Book, Chapter


@dataclass(frozen=True)
class BookDiff:
    added_chapter_ids: tuple[str, ...]
    removed_chapter_ids: tuple[str, ...]
    changed_chapter_ids: tuple[str, ...]
    changed_knowledge_unit_ids: tuple[str, ...]


def _dedupe_preserve_order(items: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _chapter_changed(old: Chapter, new: Chapter, *, old_index: int, new_index: int) -> bool:
    return (
        old.book_id != new.book_id
        or old.stable_key != new.stable_key
        or old.title != new.title
        or old.order != new.order
        or old.source_knowledge_unit_ids != new.source_knowledge_unit_ids
        or old.publication_version != new.publication_version
        or old_index != new_index
    )


def _source_ku_delta(old: Chapter | None, new: Chapter | None) -> tuple[str, ...]:
    if old is None and new is None:
        return ()
    if old is None:
        return _dedupe_preserve_order(tuple(new.source_knowledge_unit_ids))
    if new is None:
        return _dedupe_preserve_order(tuple(old.source_knowledge_unit_ids))

    old_kus = tuple(old.source_knowledge_unit_ids)
    new_kus = tuple(new.source_knowledge_unit_ids)
    if old_kus == new_kus:
        return ()

    old_set = set(old_kus)
    new_set = set(new_kus)
    delta: list[str] = []
    for ku_id in old_kus:
        if ku_id not in new_set and ku_id not in delta:
            delta.append(ku_id)
    for ku_id in new_kus:
        if ku_id not in old_set and ku_id not in delta:
            delta.append(ku_id)
    return tuple(delta)


def compute_book_diff(
    old: Book,
    new: Book,
    *,
    old_chapters: tuple[Chapter, ...] = (),
    new_chapters: tuple[Chapter, ...] = (),
) -> BookDiff:
    old_ids = _dedupe_preserve_order(tuple(old.chapter_ids))
    new_ids = _dedupe_preserve_order(tuple(new.chapter_ids))
    old_chapter_map = {chapter.id: chapter for chapter in old_chapters}
    new_chapter_map = {chapter.id: chapter for chapter in new_chapters}

    added_chapter_ids = tuple(chapter_id for chapter_id in new_ids if chapter_id not in old_chapter_map)
    removed_chapter_ids = tuple(chapter_id for chapter_id in old_ids if chapter_id not in new_chapter_map)

    changed_chapter_ids: list[str] = []
    changed_knowledge_unit_ids: list[str] = []
    seen_kus: set[str] = set()

    old_positions = {chapter_id: index for index, chapter_id in enumerate(old_ids)}
    new_positions = {chapter_id: index for index, chapter_id in enumerate(new_ids)}

    def _append_ku_delta(chapter_id: str) -> None:
        old_chapter = old_chapter_map.get(chapter_id)
        new_chapter = new_chapter_map.get(chapter_id)
        for ku_id in _source_ku_delta(old_chapter, new_chapter):
            if ku_id not in seen_kus:
                seen_kus.add(ku_id)
                changed_knowledge_unit_ids.append(ku_id)

    for chapter_id in new_ids:
        old_chapter = old_chapter_map.get(chapter_id)
        new_chapter = new_chapter_map.get(chapter_id)
        if old_chapter is None or new_chapter is None:
            continue
        if _chapter_changed(
            old_chapter,
            new_chapter,
            old_index=old_positions[chapter_id],
            new_index=new_positions[chapter_id],
        ):
            changed_chapter_ids.append(chapter_id)

    for chapter_id in removed_chapter_ids:
        _append_ku_delta(chapter_id)

    for chapter_id in old_ids:
        if chapter_id not in old_chapter_map or chapter_id not in new_chapter_map:
            continue
        old_chapter = old_chapter_map[chapter_id]
        new_chapter = new_chapter_map[chapter_id]
        if _chapter_changed(
            old_chapter,
            new_chapter,
            old_index=old_positions[chapter_id],
            new_index=new_positions[chapter_id],
        ):
            _append_ku_delta(chapter_id)

    for chapter_id in added_chapter_ids:
        _append_ku_delta(chapter_id)

    return BookDiff(
        added_chapter_ids=added_chapter_ids,
        removed_chapter_ids=removed_chapter_ids,
        changed_chapter_ids=tuple(changed_chapter_ids),
        changed_knowledge_unit_ids=tuple(changed_knowledge_unit_ids),
    )


def affected_chapters(
    chapters: tuple[Chapter, ...],
    knowledge_unit_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not chapters or not knowledge_unit_ids:
        return ()

    changed_ids = set(_dedupe_preserve_order(knowledge_unit_ids))
    affected: list[str] = []
    seen: set[str] = set()
    for chapter in chapters:
        if chapter.id in seen:
            continue
        if changed_ids.intersection(chapter.source_knowledge_unit_ids):
            seen.add(chapter.id)
            affected.append(chapter.id)
    return tuple(affected)


__all__ = ["BookDiff", "affected_chapters", "compute_book_diff"]
