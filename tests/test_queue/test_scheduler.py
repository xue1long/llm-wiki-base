"""Tests for select_next_task — pure function, no IO, no globals.

The scheduler picks the next task to dispatch:
- prefer_task_id (when set): pick that exact task if it's PENDING and
  not in flight. This is the explicit-dispatch path used by enqueue_task.
- otherwise: pick the earliest PENDING task not in flight.
- returns None if no candidate matches.
"""
import pytest

from src.queue.scheduler import select_next_task
from src.queue.in_flight import InMemoryInFlightTracker
from src.types import KnowledgeTask, SourceType, TaskStatus
from datetime import datetime


class FakeBackend:
    """Minimal in-memory QueueBackend for testing select_next_task."""
    def __init__(self, tasks: list[KnowledgeTask] | None = None):
        self._tasks = list(tasks or [])

    def enqueue(self, task): self._tasks.append(task)
    def save(self, task):
        for i, t in enumerate(self._tasks):
            if t.id == task.id:
                self._tasks[i] = task
                return
        self._tasks.append(task)
    def find(self, task_id):
        return next((t for t in self._tasks if t.id == task_id), None)
    def snapshot(self, *, in_flight_ids=None): return list(self._tasks)


def _mk_task(task_id: str, status: TaskStatus = TaskStatus.PENDING,
             created_at: int = 0) -> KnowledgeTask:
    return KnowledgeTask(
        id=task_id, source=f"src-{task_id}", source_type=SourceType.FILE,
        status=status, task_hash=f"hash-{task_id}", created_at=created_at,
        updated_at=created_at, retry_count=0,
    )


class TestSelectNextTask:
    def test_returns_none_when_no_pending(self):
        backend = FakeBackend([_mk_task("a", TaskStatus.APPROVED)])
        tracker = InMemoryInFlightTracker()
        assert select_next_task(backend, tracker) is None

    def test_picks_first_pending(self):
        backend = FakeBackend([
            _mk_task("a", created_at=1),
            _mk_task("b", created_at=2),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker)
        assert result is not None
        assert result.id == "a"

    def test_prefers_explicit_task_id(self):
        backend = FakeBackend([
            _mk_task("a", created_at=1),
            _mk_task("b", created_at=2),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker, prefer_task_id="b")
        assert result.id == "b"

    def test_skips_in_flight(self):
        backend = FakeBackend([_mk_task("a"), _mk_task("b")])
        tracker = InMemoryInFlightTracker()
        tracker.acquire("a")
        result = select_next_task(backend, tracker)
        assert result.id == "b"

    def test_preferred_task_id_skipped_if_in_flight(self):
        backend = FakeBackend([_mk_task("a"), _mk_task("b")])
        tracker = InMemoryInFlightTracker()
        tracker.acquire("b")
        result = select_next_task(backend, tracker, prefer_task_id="b")
        assert result is None

    def test_preferred_task_id_skipped_if_not_pending(self):
        backend = FakeBackend([_mk_task("a", TaskStatus.RUNNING)])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker, prefer_task_id="a")
        assert result is None

    def test_picks_only_pending_status(self):
        backend = FakeBackend([
            _mk_task("a", TaskStatus.RUNNING),
            _mk_task("b", TaskStatus.PENDING),
        ])
        tracker = InMemoryInFlightTracker()
        result = select_next_task(backend, tracker)
        assert result.id == "b"
