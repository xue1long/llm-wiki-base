"""LifecycleEngine — 8-state 15-edge state machine for KnowledgeObject lifecycle."""
import time

from src.events.event_bus import event_bus as _default_event_bus
from src.knowledge.core.object import KnowledgeObject, LifecycleState


# ---------------------------------------------------------------------------
# Valid transition map: {from_state: {to_state, ...}}
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.CREATED:     {LifecycleState.PROCESSING, LifecycleState.ARCHIVED},
    LifecycleState.PROCESSING:  {LifecycleState.REVIEWING, LifecycleState.FAILED, LifecycleState.ARCHIVED},
    LifecycleState.REVIEWING:   {LifecycleState.ACTIVE, LifecycleState.REJECTED, LifecycleState.PROCESSING},
    LifecycleState.ACTIVE:      {LifecycleState.DEPRECATED, LifecycleState.ARCHIVED},
    LifecycleState.DEPRECATED:  {LifecycleState.ACTIVE, LifecycleState.ARCHIVED},
    LifecycleState.FAILED:      {LifecycleState.PROCESSING, LifecycleState.ARCHIVED},
    LifecycleState.REJECTED:    {LifecycleState.ARCHIVED},
    LifecycleState.ARCHIVED:    set(),  # terminal
}


# ---------------------------------------------------------------------------
# Task status → LifecycleState mapping
# ---------------------------------------------------------------------------

_TASK_STATUS_MAP: dict[str, LifecycleState | None] = {
    "PENDING":          None,
    "RUNNING":          LifecycleState.PROCESSING,
    "WAITING_REVIEW":   LifecycleState.REVIEWING,
    "APPROVED":         LifecycleState.ACTIVE,
    "REJECTED":         LifecycleState.REJECTED,
    "FAILED":           LifecycleState.FAILED,
    "ARCHIVED":         LifecycleState.ARCHIVED,
    "TIMEOUT":          LifecycleState.ARCHIVED,
    "DEAD_LETTER":      LifecycleState.FAILED,
}


def task_status_to_lifecycle(task_status: str) -> LifecycleState | None:
    """Map a Queue task status string to a LifecycleState.

    Returns None for PENDING (no KnowledgeObject exists yet).
    Raises ValueError for unknown status strings.
    """
    status_upper = task_status.upper()
    if status_upper not in _TASK_STATUS_MAP:
        raise ValueError(
            f"Unknown task status: {task_status!r}. "
            f"Known statuses: {sorted(_TASK_STATUS_MAP.keys())}"
        )
    return _TASK_STATUS_MAP[status_upper]


# ---------------------------------------------------------------------------
# LifecycleEngine
# ---------------------------------------------------------------------------

class LifecycleEngine:
    """State machine that governs KnowledgeObject lifecycle transitions.

    8 states, 15 valid edges. Emits ``lifecycle.changed`` events via EventBus
    on successful transitions.
    """

    def __init__(self, event_bus=None):
        self.event_bus = event_bus if event_bus is not None else _default_event_bus

    # ---- query ----------------------------------------------------------

    def can_transition(self, prev: LifecycleState, next: LifecycleState) -> bool:
        """Return True if *prev* → *next* is a valid transition."""
        if prev == next:
            return False
        return next in _VALID_TRANSITIONS.get(prev, set())

    # ---- mutate ----------------------------------------------------------

    def transition(
        self,
        obj: KnowledgeObject,
        new_state: LifecycleState,
        reason: str,
    ) -> KnowledgeObject:
        """Transition *obj* to *new_state*, mutating it in-place.

        Returns the same object (mutated).  Raises ``ValueError`` if the
        transition is not allowed.
        """
        if not self.can_transition(obj.lifecycle, new_state):
            raise ValueError(
                f"Illegal transition: {obj.lifecycle.value!r} → {new_state.value!r} "
                f"(reason: {reason!r})"
            )

        prev_state = obj.lifecycle
        obj.lifecycle = new_state
        obj.updated_at = int(time.time() * 1000)

        self.event_bus.emit("lifecycle.changed", {
            "event": "lifecycle.changed",
            "object_id": obj.id,
            "from": prev_state.value,
            "to": new_state.value,
            "reason": reason,
            "timestamp": obj.updated_at,
        })

        return obj
