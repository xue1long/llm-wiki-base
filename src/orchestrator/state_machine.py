# ruflo-kb/src/orchestrator/state_machine.py
from ..types import TaskStatus

VALID_TRANSITIONS = {
    (TaskStatus.PENDING, TaskStatus.RUNNING),
    (TaskStatus.RUNNING, TaskStatus.WAITING_REVIEW),
    (TaskStatus.WAITING_REVIEW, TaskStatus.APPROVED),
    (TaskStatus.WAITING_REVIEW, TaskStatus.REJECTED),
    (TaskStatus.REJECTED, TaskStatus.ARCHIVED),
    (TaskStatus.REJECTED, TaskStatus.PENDING),  # retry
    (TaskStatus.APPROVED, TaskStatus.ARCHIVED),
    (TaskStatus.FAILED, TaskStatus.PENDING),     # retry
    (TaskStatus.FAILED, TaskStatus.ARCHIVED),
    (TaskStatus.TIMEOUT, TaskStatus.PENDING),    # retry
    (TaskStatus.TIMEOUT, TaskStatus.ARCHIVED),
}

def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    return (from_status, to_status) in VALID_TRANSITIONS

EVENT_TO_STATUS = {
    "collector:done": TaskStatus.RUNNING,
    "processor:done": TaskStatus.WAITING_REVIEW,
    "librarian:done": TaskStatus.APPROVED,
    "audit:pass": TaskStatus.APPROVED,
    "audit:fail": TaskStatus.REJECTED,
}

def get_next_status(current: TaskStatus, event: str) -> TaskStatus | None:
    return EVENT_TO_STATUS.get(event)
