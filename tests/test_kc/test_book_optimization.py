from __future__ import annotations

from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.views.book import (
    BookChapterRegistry,
    BookJobState,
    BookPublicationState,
    BookUpdateScheduler,
    Chapter,
    MappingCache,
    can_transition_job,
    can_transition_publication,
    map_ku_to_chapter,
)


def _ku(title: str = "title") -> KnowledgeUnit:
    return KnowledgeUnit(
        ku_id="ku-1", concept_id="concept-1", question="q", title=title,
        unit_type="definition", knowledge_mode="observed",
    )


def _registry() -> BookChapterRegistry:
    return BookChapterRegistry((Chapter(
        id="ch-1", book_id="book-1", stable_key="concept-1::definition",
        title="Chapter", order=1,
    ),))


def test_mapping_cache_reuses_and_persists_versioned_decision(tmp_path):
    path = tmp_path / "mapping.json"
    first = MappingCache(path)
    expected = map_ku_to_chapter(_ku(), _registry())
    assert first.resolve(_ku(), _registry()) == expected
    assert first.resolve(_ku(), _registry()).chapter_id == "ch-1"
    assert first.hits == 1

    second = MappingCache(path)
    assert second.resolve(_ku("renamed"), _registry(), model="new-model").chapter_id == "ch-1"
    assert second.misses == 1


def test_book_update_scheduler_coalesces_updates_and_flushes_sorted():
    calls = []
    scheduler = BookUpdateScheduler(lambda book, wikis: calls.append((book, wikis)), delay=60, batch_size=3)
    scheduler.schedule("book-1", "wiki-2")
    scheduler.schedule("book-1", "wiki-1")
    scheduler.flush("book-1")
    assert calls == [("book-1", ("wiki-1", "wiki-2"))]


def test_book_states_keep_content_and_job_transitions_separate():
    assert can_transition_publication(BookPublicationState.AVAILABLE, BookPublicationState.OUTDATED)
    assert can_transition_job(BookJobState.COMPILING, BookJobState.FAILED)
    assert not can_transition_publication(BookPublicationState.OUTDATED, BookPublicationState.OUTDATED)
