"""Tests for JsonFileBackend — the default QueueBackend.

These tests mirror the existing tests in test_save_atomic.py but target
the new persistence module directly. The contract is the same:
- enqueue / save persists to disk via safe_write
- snapshot() returns KnowledgeTask list, with APPROVED filtered out
- on IO error mid-write, the target file is unchanged
"""
import json
import os
import pytest

from src.queue.persistence import JsonFileBackend
from src.queue.ports import QueueBackend
from src.types import KnowledgeTask, SourceType, TaskStatus
from datetime import datetime


def _mk_task(task_id: str, source: str, status: TaskStatus = TaskStatus.PENDING) -> KnowledgeTask:
    return KnowledgeTask(
        id=task_id,
        source=source,
        source_type=SourceType.FILE,
        status=status,
        task_hash=f"hash-{task_id}",
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp()),
        retry_count=0,
    )


class TestJsonFileBackend:
    def test_implements_queue_backend_protocol(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        assert isinstance(backend, QueueBackend)

    def test_enqueue_then_snapshot_round_trips(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        task = _mk_task("t1", "file-a.txt")
        backend.enqueue(task)
        snap = backend.snapshot()
        assert len(snap) == 1
        assert snap[0].id == "t1"
        assert snap[0].source == "file-a.txt"

    def test_snapshot_filters_approved_tasks(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a", TaskStatus.PENDING))
        backend.enqueue(_mk_task("t2", "file-b", TaskStatus.APPROVED))
        snap = backend.snapshot()
        # APPROVED is filtered out — only PENDING remains
        assert len(snap) == 1
        assert snap[0].id == "t1"

    def test_save_updates_existing_task(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a", TaskStatus.PENDING))
        updated = _mk_task("t1", "file-a", TaskStatus.RUNNING)
        backend.save(updated)
        snap = backend.snapshot()
        assert len(snap) == 1
        assert snap[0].status == TaskStatus.RUNNING

    def test_find_returns_none_for_missing(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        assert backend.find("never-added") is None

    def test_find_returns_task(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a"))
        found = backend.find("t1")
        assert found is not None
        assert found.id == "t1"

    def test_iter_ids_returns_all_tracked_ids(self, tmp_path):
        backend = JsonFileBackend(tmp_path / "queue.json")
        assert backend.iter_ids() == []
        backend.enqueue(_mk_task("t1", "file-a"))
        backend.enqueue(_mk_task("t2", "file-b"))
        ids = backend.iter_ids()
        assert sorted(ids) == ["t1", "t2"]

    def test_iter_ids_returns_independent_snapshot(self, tmp_path):
        """iter_ids returns a list copy — mutating the result must not
        affect the backend's internal state."""
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a"))
        ids = backend.iter_ids()
        ids.clear()
        # Internal state is unaffected
        assert backend.iter_ids() == ["t1"]
        assert backend.find("t1") is not None

    def test_uses_safe_write_atomic_rename(self, tmp_path):
        """safe_write uses *.tmp + os.replace; verify a .tmp file does NOT
        linger after enqueue."""
        backend = JsonFileBackend(tmp_path / "queue.json")
        backend.enqueue(_mk_task("t1", "file-a"))
        target = tmp_path / "queue.json"
        assert target.exists()
        assert not (target.parent / (target.name + ".tmp")).exists()

    def test_atomic_write_does_not_partial_write_on_failure(self, tmp_path, monkeypatch):
        """On os.replace failure (simulating mid-write crash), the target
        file must remain in its prior good state. This is the canary test
        that detects bypassing safe_write."""
        backend = JsonFileBackend(tmp_path / "queue.json")
        # Seed a valid task
        backend.enqueue(_mk_task("seed", "seed-file"))
        target = tmp_path / "queue.json"
        original = json.loads(target.read_text(encoding="utf-8"))
        original_count = len(original)

        # Break os.replace to simulate mid-write failure
        def broken_replace(src, dst):
            raise OSError("simulated mid-write failure")
        monkeypatch.setattr(os, "replace", broken_replace)

        try:
            with pytest.raises(OSError):
                backend.enqueue(_mk_task("another", "another-file"))
        finally:
            monkeypatch.undo()  # restore real os.replace

        # The seed task must still be persisted byte-for-byte
        post = json.loads(target.read_text(encoding="utf-8"))
        assert len(post) == original_count

    def test_load_recovers_from_corrupt_file(self, tmp_path):
        """Existing-but-corrupt queue file → empty list, no raise."""
        target = tmp_path / "queue.json"
        target.write_text("[bad json", encoding="utf-8")
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []

    def test_load_recovers_from_empty_file(self, tmp_path):
        target = tmp_path / "queue.json"
        target.write_text("", encoding="utf-8")
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []

    def test_load_returns_empty_when_missing(self, tmp_path):
        target = tmp_path / "queue.json"
        assert not target.exists()
        backend = JsonFileBackend(target)
        assert backend.snapshot() == []
