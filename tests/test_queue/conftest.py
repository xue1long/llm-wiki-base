"""Shared fixtures for queue tests.

Fake implementations of QueueBackend, InFlightTracker, and EventEmitter
that allow QueueService to be unit-tested without IO.

Also exposes autouse fixtures for test isolation: clear the idempotency
cache, reset the default queue singleton, and reset the queue's circuit
breaker between every test in the queue package.
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

    def find_by_hash(self, task_hash: str) -> list:
        """Return all tasks with the given task_hash."""
        return [t for t in self._tasks.values()
                if getattr(t, 'task_hash', None) == task_hash]

    def remove(self, task_id: str) -> None:
        """Remove a task from the backend."""
        self._calls.append(("remove", task_id))
        self._tasks.pop(task_id, None)

    def iter_ids(self):
        return list(self._tasks.keys())

    def snapshot(self, *, in_flight_ids=None):
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


@pytest.fixture(autouse=True)
def _reset_default_queue_singleton(tmp_path, monkeypatch):
    """Reset the default queue singleton between tests.

    Tests that go through the public enqueue_task/update_task_status
    API hit the default singleton. Without this reset, the queue state
    (tasks, in-flight, paused) leaks across tests because the singleton
    is process-wide.

    The fix: reset the singleton before each test, point its backend at
    a per-test tmp_path, and clear the persisted .kb-queue.json so the
    backend reloads to an empty state.
    """
    from src.queue import __reset_for_testing, get_default_queue_service
    from src.circuit_breaker import get_circuit_breaker, CircuitState

    monkeypatch.chdir(tmp_path)
    __reset_for_testing()
    # Rebuild the singleton now (it will pick up the tmp_path CWD)
    service = get_default_queue_service()
    # Reset the circuit breaker so prior failures don't leak
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0
    breaker.success_count = 0
    breaker.opened_at = None

    yield service
    __reset_for_testing()


@pytest.fixture
def fake_backend():
    return FakeQueueBackend()


@pytest.fixture
def fake_tracker():
    return InMemoryInFlightTracker()


@pytest.fixture
def fake_emitter():
    return FakeEventEmitter()