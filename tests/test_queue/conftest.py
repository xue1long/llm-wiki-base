"""Shared fixtures for queue tests.

Fake implementations of QueueBackend, InFlightTracker, and EventEmitter
that allow QueueService to be unit-tested without IO.
"""
from __future__ import annotations
import pytest

from src.queue.in_flight import InMemoryInFlightTracker
from src.queue.ports import QueueBackend
from src.types import KnowledgeTask


class FakeQueueBackend:
    """In-memory QueueBackend that records all calls for assertion."""

    def __init__(self) -> None:
        self._tasks: dict[str, KnowledgeTask] = {}
        self._calls: list[tuple] = []

    def enqueue(self, task: KnowledgeTask) -> None:
        self._calls.append(("enqueue", task.id))
        self._tasks[task.id] = task

    def save(self, task: KnowledgeTask) -> None:
        self._calls.append(("save", task.id))
        self._tasks[task.id] = task

    def find(self, task_id: str):
        return self._tasks.get(task_id)

    def snapshot(self):
        return list(self._tasks.values())

    def calls_matching(self, op: str):
        return [c for c in self._calls if c[0] == op]


class FakeEventEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def emit(self, event: str, payload) -> None:
        self.events.append((event, payload))


@pytest.fixture(autouse=True)
def _clear_idempotency_cache():
    """Reset the global idempotency cache between tests so the dedup
    check in QueueService.enqueue does not bleed across test cases."""
    from src.utils.idempotency import get_idempotency_cache
    get_idempotency_cache().clear()
    yield
    get_idempotency_cache().clear()


@pytest.fixture
def fake_backend():
    return FakeQueueBackend()


@pytest.fixture
def fake_tracker():
    return InMemoryInFlightTracker()


@pytest.fixture
def fake_emitter():
    return FakeEventEmitter()
