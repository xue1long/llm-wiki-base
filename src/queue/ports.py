"""Protocols (PEP 544) for queue subsystem dependencies.

These are duck-typed contracts; concrete implementations live in
persistence.py, in_flight.py, retry.py. The point is that QueueService
can be constructed with any combination of implementations — the default
ones in production, fakes in tests, or alternative adapters in future.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable

from ..types import KnowledgeTask


# Forward declarations for the RetryPolicy protocol — RetryDecision is
# defined in retry.py. We import lazily inside the method body if needed,
# but a Protocol can use a forward reference string.
class _RetryLike(Protocol):
    def can_execute(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...


@runtime_checkable
class QueueBackend(Protocol):
    """Persists and queries tasks. Default impl: JsonFileBackend."""

    def enqueue(self, task: KnowledgeTask) -> None: ...

    def save(self, task: KnowledgeTask) -> None: ...

    def remove(self, task_id: str) -> None:
        """Remove a task from the backend. Used when re-enqueueing a failed task."""

    def find(self, task_id: str) -> KnowledgeTask | None: ...

    def find_by_hash(self, task_hash: str) -> list[KnowledgeTask]:
        """Return all tasks with the given task_hash. Used to detect duplicates."""

    def iter_ids(self) -> list[str]:
        """Return a snapshot of all currently tracked task ids. Used by
        callers (e.g. QueueService.get_queue) that want to enumerate the
        full set without constructing a full object per row."""
        ...

    def snapshot(self) -> list[KnowledgeTask]:
        """Return a copy of all currently tracked tasks. Implementations
        may filter out terminal states (e.g. APPROVED) — see the
        APPROVED-filtering invariant in the spec."""
        ...


@runtime_checkable
class InFlightTracker(Protocol):
    """Tracks which task_ids are currently being processed.

    Concurrency: acquire must be idempotent — two threads racing on the
    same task_id must see at most one True return. Default impl uses an
    internal lock.
    """

    def acquire(self, task_id: str) -> bool: ...

    def release(self, task_id: str) -> None: ...

    def is_in_flight(self, task_id: str) -> bool: ...

    def snapshot(self) -> set[str]: ...


@runtime_checkable
class EventEmitter(Protocol):
    """Dispatches events. Default impl: src.events.event_bus.EventBus."""

    def emit(self, event: str, payload) -> None: ...


@runtime_checkable
class RetryPolicy(Protocol):
    """Decides what to do after a status change (e.g. retry vs dead-letter)."""

    def decide(self, task: KnowledgeTask, attempted_status, error: str | None,
               breaker: _RetryLike): ...
