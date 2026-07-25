"""Pure state machine for KnowledgeTask transitions. No IO, no globals.

This is the source of truth for which task status transitions are legal.
The current `update_task_status` in `src/queue/queue.py:103-107` calls a
local `can_transition`; this module is the extracted pure form. The
existing module is migrated to import from here.

The matrix below is the production source of truth — it matches the
matrix previously in `src/orchestrator/state_machine.py` (15 entries).
"""
from __future__ import annotations
from ..types import TaskStatus


class InvalidTransition(Exception):
    """Raised when a task status change violates the state machine."""

    def __init__(self, task_id: str, prev_status: str, next_status: str):
        super().__init__(task_id, prev_status, next_status)
        self.task_id = task_id
        self.prev_status = prev_status
        self.next_status = next_status


# Legal transitions (production matrix — same as the previous
# orchestrator/state_machine.py):
#   PENDING        → RUNNING
#   RUNNING        → WAITING_REVIEW | APPROVED | FAILED
#   WAITING_REVIEW → APPROVED | REJECTED
#   REJECTED       → ARCHIVED | PENDING (retry)
#   APPROVED       → ARCHIVED
#   FAILED         → PENDING (retry) | ARCHIVED | DEAD_LETTER (retry exhaustion)
#   TIMEOUT        → PENDING (retry) | ARCHIVED | DEAD_LETTER (retry exhaustion)
#   DEAD_LETTER    → (terminal)
_LEGAL: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset({
    (TaskStatus.PENDING, TaskStatus.RUNNING),
    (TaskStatus.PENDING, TaskStatus.FAILED),
    (TaskStatus.RUNNING, TaskStatus.WAITING_REVIEW),
    (TaskStatus.RUNNING, TaskStatus.APPROVED),
    (TaskStatus.RUNNING, TaskStatus.FAILED),
    (TaskStatus.WAITING_REVIEW, TaskStatus.APPROVED),
    (TaskStatus.WAITING_REVIEW, TaskStatus.REJECTED),
    (TaskStatus.REJECTED, TaskStatus.ARCHIVED),
    (TaskStatus.REJECTED, TaskStatus.PENDING),
    (TaskStatus.APPROVED, TaskStatus.ARCHIVED),
    (TaskStatus.FAILED, TaskStatus.PENDING),
    (TaskStatus.FAILED, TaskStatus.ARCHIVED),
    (TaskStatus.FAILED, TaskStatus.DEAD_LETTER),
    (TaskStatus.TIMEOUT, TaskStatus.PENDING),
    (TaskStatus.TIMEOUT, TaskStatus.ARCHIVED),
    (TaskStatus.TIMEOUT, TaskStatus.DEAD_LETTER),
})


def can_transition(prev: TaskStatus, next_: TaskStatus) -> bool:
    """Return True if `prev → next_` is a legal status transition."""
    return (prev, next_) in _LEGAL