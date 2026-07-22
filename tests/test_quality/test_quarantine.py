"""Tests for QuarantineStore."""
from src.quality.quarantine import QuarantineStore
from src.quality.types import JudgmentScores, Judgment


def _judgment(page_id="p1"):
    return Judgment(
        page_id=page_id, page_type="entity",
        scores=JudgmentScores(0.4, 0.5, 0.4, 0.5, 0.4, 0.5),
        total_score=0.45, verdict="reject",
        issues=[{"dimension": "factuality", "severity": "major"}],
    )


def test_put_writes_files(tmp_path):
    path = QuarantineStore.put(tmp_path, "task1", "p1", "# body", _judgment("p1"))
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# body"
    judgment_path = path.with_suffix("")  # .md
    sidecar = path.parent / "p1.judgment.json"
    assert sidecar.exists()
    import json
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["page_id"] == "p1"
    assert data["verdict"] == "reject"


def test_list_filters_by_task(tmp_path):
    QuarantineStore.put(tmp_path, "task1", "a", "x", _judgment("a"))
    QuarantineStore.put(tmp_path, "task2", "b", "y", _judgment("b"))
    only_task1 = QuarantineStore.list(tmp_path, task_id="task1")
    assert len(only_task1) == 1
    assert only_task1[0].name == "a.md"
    all_pages = QuarantineStore.list(tmp_path)
    assert len(all_pages) == 2


def test_list_empty(tmp_path):
    assert QuarantineStore.list(tmp_path) == []
    assert QuarantineStore.list(tmp_path, task_id="nonexistent") == []
