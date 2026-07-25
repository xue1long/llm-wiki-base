"""Tests for atomic save semantics of src.queue (via JsonFileBackend).

Verifies C-6 fix: JsonFileBackend._save_unlocked writes via safe_write
(tmp + os.replace under the hood), so writes are atomic and the target
file is never partial. On JSONDecodeError / OSError the backend
recovers to an empty state rather than raising.

After the queue refactor (Tasks 1-7), the production persistence is
delegated to JsonFileBackend via QueueService. This test exercises
JsonFileBackend directly with the same atomic-write contract.
"""
import json
import os
import pytest
from pathlib import Path

from src.queue import enqueue_task
from src.queue import __reset_for_testing
from src.queue.persistence import JsonFileBackend
from src.types import SourceType
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()


def test_save_writes_via_tmp_then_replace(tmp_path, monkeypatch):
    """JsonFileBackend uses safe_write so target file is never partial."""
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", SourceType.FILE, "hash-1")
    target = tmp_path / ".kb-queue.json"
    # Target exists with the persisted content
    assert target.exists()
    # And the .tmp file has been replaced (not lingering)
    assert not target.with_name(target.name + ".tmp").exists()


def test_save_does_not_leak_tmp_on_subsequent_save(tmp_path, monkeypatch):
    """Multiple saves do not leave .tmp residue."""
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", SourceType.FILE, "hash-1")
    enqueue_task("t2", SourceType.FILE, "hash-2")
    target = tmp_path / ".kb-queue.json"
    assert target.exists()
    assert not (tmp_path / (".kb-queue.json" + ".tmp")).exists()
    assert not target.with_name(target.name + ".tmp").exists()


def test_load_recovers_from_truncated_queue(tmp_path):
    """Existing-but-corrupt queue file → empty list (no raise)."""
    target = tmp_path / "queue.json"
    target.write_text('[{"task_id": "t1"', encoding="utf-8")
    backend = JsonFileBackend(target)
    snap = backend.snapshot()
    assert snap == []


def test_load_recovers_from_empty_file(tmp_path):
    """Zero-byte queue file → empty list (no raise)."""
    target = tmp_path / "queue.json"
    target.write_text("", encoding="utf-8")
    backend = JsonFileBackend(target)
    snap = backend.snapshot()
    assert snap == []


def test_load_returns_empty_when_missing(tmp_path):
    """Missing queue file → empty list."""
    target = tmp_path / "queue.json"
    assert not target.exists()
    backend = JsonFileBackend(target)
    snap = backend.snapshot()
    assert snap == []


def test_load_recovers_from_garbage(tmp_path):
    """Non-JSON content → empty list (no raise)."""
    target = tmp_path / "queue.json"
    target.write_text("not even close to json", encoding="utf-8")
    backend = JsonFileBackend(target)
    snap = backend.snapshot()
    assert snap == []


def test_round_trip_persists_tasks(tmp_path):
    """Tasks saved are recovered on a fresh JsonFileBackend load."""
    backend = JsonFileBackend(tmp_path / "queue.json")
    from datetime import datetime
    from src.types import KnowledgeTask, TaskStatus
    t1 = KnowledgeTask(
        id="a", source="a-source", source_type=SourceType.FILE,
        status=TaskStatus.PENDING, task_hash="hash-a",
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp()),
        retry_count=0,
    )
    t2 = KnowledgeTask(
        id="b", source="b-source", source_type=SourceType.URL,
        status=TaskStatus.PENDING, task_hash="hash-b",
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp()),
        retry_count=0,
    )
    backend.enqueue(t1)
    backend.enqueue(t2)

    fresh = JsonFileBackend(tmp_path / "queue.json")
    snap = fresh.snapshot()
    assert len(snap) == 2
    sources = {t.source for t in snap}
    assert sources == {"a-source", "b-source"}


def test_atomic_write_does_not_partial_write(tmp_path, monkeypatch):
    """On any IO failure mid-save, the target file must remain the prior good state.

    We monkeypatch os.replace (the C-level function that src/lib/write_hooks.py
    calls in its atomic-write primitive) to raise — the original target must
    remain untouched. Note: we patch os.replace, NOT Path.replace, because
    safe_write uses the module-level os.replace function. Patching Path.replace
    would be a no-op against the production code path.
    """
    monkeypatch.chdir(tmp_path)
    # Seed a valid queue via the public enqueue_task path
    enqueue_task("seed", SourceType.FILE, "seed-hash")
    target = tmp_path / ".kb-queue.json"
    assert target.exists()
    original = target.read_text(encoding="utf-8")
    original_tasks = json.loads(original)

    # Simulate a mid-write failure by breaking os.replace (the function
    # safe_write actually invokes in src/lib/write_hooks.py).
    def broken_replace(src, dst):
        raise OSError("simulated mid-write failure")

    monkeypatch.setattr(os, "replace", broken_replace)
    try:
        enqueue_task("another", SourceType.FILE, "another-hash")
    except OSError:
        pass  # ok — what matters is target state

    # Restore real os.replace via monkeypatch.undo (safer than manually re-binding)
    monkeypatch.undo()

    # Target file must still hold the exact original content — the failed
    # os.replace means the new content never reached the target, so the file
    # is byte-for-byte unchanged from before the failed save.
    assert target.exists()
    post = json.loads(target.read_text(encoding="utf-8"))
    assert post == original_tasks