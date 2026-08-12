"""Persistence contract for ingest task history."""
from types import SimpleNamespace

from src.server import ingest_tracker


def test_task_history_survives_tracker_reload(monkeypatch, tmp_path):
    path = tmp_path / "ingest_tasks.json"
    monkeypatch.setattr(ingest_tracker, "_tasks_path", lambda project_id: path)
    ingest_tracker._tasks.clear()

    ingest_tracker._on_created(SimpleNamespace(
        task_id="task-1", source="raw/sources/book.md", project_id="u",
    ))
    assert ingest_tracker.list_tasks("u")[0]["task_id"] == "task-1"

    ingest_tracker._tasks.clear()
    assert ingest_tracker.list_tasks("u")[0]["source"] == "raw/sources/book.md"
