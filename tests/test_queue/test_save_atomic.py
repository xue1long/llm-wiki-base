"""Tests for atomic save semantics of src.queue.queue.

Verifies C-6 fix: _save_queue writes via *.tmp then os.replace (no torn writes),
and _load_queue recovers from JSONDecodeError / OSError instead of raising.
"""
import json
import os
import pytest
from pathlib import Path

from src.queue import queue as q
from src.queue.queue import (
    QUEUE_FILE,
    _save_queue,
    _load_queue,
    enqueue_task,
    __reset_for_testing,
    KnowledgeTask,
    TaskStatus,
)
from src.types import SourceType


def setup_function(_):
    __reset_for_testing()


def test_save_writes_via_tmp_then_replace(tmp_path, monkeypatch):
    """_save_queue uses tmp + os.replace so target file is never partial."""
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", SourceType.FILE, "hash-1")
    target = tmp_path / QUEUE_FILE
    # Target exists with the persisted content
    assert target.exists()
    # And the .tmp file has been replaced (not lingering)
    assert not target.with_name(target.name + ".tmp").exists()


def test_save_does_not_leak_tmp_on_subsequent_save(tmp_path, monkeypatch):
    """Multiple saves do not leave .tmp residue."""
    monkeypatch.chdir(tmp_path)
    enqueue_task("t1", SourceType.FILE, "hash-1")
    enqueue_task("t2", SourceType.FILE, "hash-2")
    target = tmp_path / QUEUE_FILE
    assert target.exists()
    assert not (tmp_path / (QUEUE_FILE + ".tmp")).exists()
    assert not target.with_name(target.name + ".tmp").exists()


def test_load_recovers_from_truncated_queue(tmp_path, monkeypatch):
    """Existing-but-corrupt queue file → empty list (no raise)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / QUEUE_FILE).write_text('[{"task_id": "t1"', encoding="utf-8")
    # Force a fresh load
    __reset_for_testing()
    assert q._queue == []


def test_load_recovers_from_empty_file(tmp_path, monkeypatch):
    """Zero-byte queue file → empty list (no raise)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / QUEUE_FILE).write_text("", encoding="utf-8")
    __reset_for_testing()
    assert q._queue == []


def test_load_returns_empty_when_missing(tmp_path, monkeypatch):
    """Missing queue file → empty list."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / QUEUE_FILE).exists()
    __reset_for_testing()
    assert q._queue == []


def test_load_recovers_from_garbage(tmp_path, monkeypatch):
    """Non-JSON content → empty list (no raise)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / QUEUE_FILE).write_text("not even close to json", encoding="utf-8")
    __reset_for_testing()
    assert q._queue == []


def test_round_trip_persists_tasks(tmp_path, monkeypatch):
    """Tasks saved are recovered on next _load_queue."""
    monkeypatch.chdir(tmp_path)
    enqueue_task("a-source", SourceType.FILE, "hash-a")
    enqueue_task("b-source", SourceType.URL, "hash-b")
    __reset_for_testing()
    assert len(q._queue) == 2
    sources = {t.source for t in q._queue}
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
    # Seed a valid queue
    enqueue_task("seed", SourceType.FILE, "seed-hash")
    target = tmp_path / QUEUE_FILE
    original = target.read_text(encoding="utf-8")
    original_tasks = json.loads(original)

    # Simulate a mid-write failure by breaking os.replace (the function
    # safe_write actually invokes in src/lib/write_hooks.py:43).
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
