"""DecayBridge — bridge between 5-pool heat system and lifecycle state machine."""
import time

from src.knowledge.core.object import LifecycleState, KnowledgeObject
from src.knowledge.core.lifecycle import LifecycleEngine


class DecayBridge:
    """Bridge between the 5-pool heat system and the lifecycle state machine.

    When an object's heat decays to zero, this bridge triggers a lifecycle
    transition to DEPRECATED. The DEPRECATED object remains searchable
    (marked as "可能过时" / "possibly outdated"), not removed.

    Per the plan:
    - Heat=0 + zombie → lifecycle → DEPRECATED (not ARCHIVED)
    - DEPRECATED objects stay searchable (not zombie limbo)
    - Curator later reviews DEPRECATED objects → ARCHIVED or RESTORED
    """

    def __init__(self, lifecycle_engine: LifecycleEngine, event_bus=None):
        self._lifecycle = lifecycle_engine
        self._event_bus = event_bus
        self._deprecated_by_heat: set[str] = set()
        self._objects: dict[str, KnowledgeObject] = {}

    # ------------------------------------------------------------------
    # Object registry
    # ------------------------------------------------------------------

    def register_object(self, obj: KnowledgeObject) -> None:
        """Register a KnowledgeObject so the bridge can manage its lifecycle."""
        self._objects[obj.id] = obj

    # ------------------------------------------------------------------
    # Heat decay callbacks
    # ------------------------------------------------------------------

    def on_heat_decayed(self, object_id: str, heat: int, is_zombie: bool) -> str | None:
        """Called when an object's heat changes.

        If heat reaches 0 and object is a zombie (zombie_since is set),
        transition lifecycle to DEPRECATED.

        Returns:
            The new LifecycleState value if transitioned, None if no
            transition was needed.
        """
        if heat != 0 or not is_zombie:
            return None

        obj = self._objects.get(object_id)
        if obj is None:
            return None
        if obj.lifecycle != LifecycleState.ACTIVE:
            return None

        try:
            self._lifecycle.transition(
                obj, LifecycleState.DEPRECATED, "heat decayed to zero"
            )
        except ValueError:
            return None

        self._deprecated_by_heat.add(object_id)
        return LifecycleState.DEPRECATED.value

    def on_heat_restored(self, object_id: str, heat: int) -> str | None:
        """Called when heat is restored above 0.

        If object was DEPRECATED due to heat decay, transition back to ACTIVE.

        Returns:
            The new LifecycleState value if transitioned, None if no
            transition was needed.
        """
        if heat <= 0 or object_id not in self._deprecated_by_heat:
            return None

        obj = self._objects.get(object_id)
        if obj is None:
            return None
        if obj.lifecycle != LifecycleState.DEPRECATED:
            return None

        try:
            self._lifecycle.transition(
                obj, LifecycleState.ACTIVE, "heat restored"
            )
        except ValueError:
            return None

        self._deprecated_by_heat.discard(object_id)
        return LifecycleState.ACTIVE.value

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_deprecated_objects(self) -> list[str]:
        """Return list of object IDs currently DEPRECATED due to heat decay."""
        return list(self._deprecated_by_heat)

    def get_decay_candidates(self, objects: list[dict]) -> list[dict]:
        """Rank objects by decay priority (most decayed first).

        Ranking factors:
        - heat score (lower = higher priority)
        - last_used_at (older = higher priority)
        - grade (C-grade decays faster than A-grade)
        - has_conflicts (conflicts = slower decay — they need resolution,
          not removal)

        Returns a new list sorted by decay priority (highest first).
        """
        now = int(time.time() * 1000)

        def _decay_score(obj: dict) -> float:
            heat = obj.get("heat", 50)
            last_used = obj.get("last_used_at", 0)
            grade = obj.get("grade", "B")
            has_conflicts = obj.get("has_conflicts", False)

            score = 0.0
            # Lower heat → higher priority
            score += (100 - heat) * 1.0
            # Older last_used → higher priority (age in days, capped at
            # one year to avoid runaway scores)
            if last_used > 0:
                age_days = (now - last_used) / (86400 * 1000)
                score += min(age_days, 365) * 0.5
            # Grade penalty: C decays faster, A decays slower
            if grade == "C":
                score += 50
            elif grade == "B":
                score += 10
            # Conflicts slow decay (they need human resolution)
            if has_conflicts:
                score -= 100

            return score

        return sorted(objects, key=_decay_score, reverse=True)
