"""select_next_task — pure function for task selection.

This is the heart of the scheduler. Given a backend (where tasks live)
and a tracker (which tasks are in flight), pick the next task to
dispatch. Pure: no IO, no globals, no side effects.
"""
from __future__ import annotations

from ..types import KnowledgeTask, TaskStatus
from .ports import InFlightTracker, QueueBackend


def select_next_task(
    backend: QueueBackend,
    tracker: InFlightTracker,
    *,
    prefer_task_id: str | None = None,
) -> KnowledgeTask | None:
    """Pick the next task to dispatch.

    Args:
        backend: source of truth for tasks.
        tracker: source of truth for in-flight task IDs.
        prefer_task_id: when set, attempt to pick that exact task first
            (used by enqueue_task's explicit-dispatch path).

    Returns:
        The chosen KnowledgeTask, or None if no candidate matches.
    """
    candidates = backend.snapshot()
    if prefer_task_id is not None:
        return next(
            (t for t in candidates
             if t.id == prefer_task_id
             and t.status == TaskStatus.PENDING
             and not tracker.is_in_flight(t.id)),
            None,
        )
    return next(
        (t for t in candidates
         if t.status == TaskStatus.PENDING
         and not tracker.is_in_flight(t.id)),
        None,
    )
