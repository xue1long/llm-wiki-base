"""Tests for QuarantineStore."""
import pytest
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


def test_put_atomic_pair_write_failure(tmp_path, monkeypatch):
    """If the page write succeeds but the judgment write raises, NEITHER
    file should be visible after the put. QuarantineStore.put wraps both
    writes in AtomicContext + safe_write so a mid-write crash leaves the
    wiki unchanged rather than torn (page-only or judgment-only).

    Per AtomicContext docstring (audit C1), an exception inside the body
    MUST NOT commit buffered writes AND the body's exception propagates
    out of put(). The bucket is cleared on exception so neither file
    reaches the filesystem.
    """
    from src.lib.write_hooks import safe_write as real_safe_write

    call_count = {"n": 0}

    def flaky_safe_write(path, content):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated write failure")
        return real_safe_write(path, content)

    monkeypatch.setattr(
        "src.quality.quarantine.safe_write", flaky_safe_write
    )

    from src.quality.quarantine import QuarantineStore
    with pytest.raises(OSError, match="simulated write failure"):
        QuarantineStore.put(
            tmp_path, "task1", "p1", "# body", _judgment("p1")
        )

    # Neither file should exist after the failed put: the bucket was
    # cleared by the atomic context exit because exc_type was set.
    page_path = tmp_path / ".index" / "quarantine" / "task1" / "p1.md"
    sidecar = tmp_path / ".index" / "quarantine" / "task1" / "p1.judgment.json"
    assert not page_path.exists(), (
        f"page file leaked after atomic rollback: {page_path}"
    )
    assert not sidecar.exists(), (
        f"judgment sidecar leaked after atomic rollback: {sidecar}"
    )
    # Both writes were attempted (page then judgment).
    assert call_count["n"] == 2
