from pathlib import Path

import pytest

from src.kc.views.book.wiki.batch_state import (
    BatchStateError,
    chapter_from_dict,
    load_or_create,
    record,
)
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection


def test_batch_state_round_trips_completed_chapter_and_resumes(tmp_path: Path):
    path = tmp_path / "batch-state.json"
    state = load_or_create(
        path, snapshot_id="snap", chapter_ids=("c1", "c2"),
        batch_size=1, max_attempts=1, max_llm_calls=4, resume=False,
    )
    chapter = GeneratedChapter(
        "c1", (GeneratedSection("s1", "Title", "Body", ("p1",)),), "complete",
        prompt_hash="prompt-1",
    )
    record(path, state, chapter, input_hash="input-1", calls=1)

    resumed = load_or_create(
        path, snapshot_id="snap", chapter_ids=("c1", "c2"),
        batch_size=1, max_attempts=1, max_llm_calls=4, resume=True,
    )
    restored = chapter_from_dict(resumed["chapters"]["c1"]["result"])
    assert restored == chapter
    assert resumed["budget"]["actual_calls"] == 1


def test_batch_state_fails_closed_on_corrupt_resume(tmp_path: Path):
    path = tmp_path / "batch-state.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(BatchStateError):
        load_or_create(
            path, snapshot_id="snap", chapter_ids=("c1",),
            batch_size=1, max_attempts=1, max_llm_calls=2, resume=True,
        )
