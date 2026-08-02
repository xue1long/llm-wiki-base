"""Test DecayBridge — heat→lifecycle DEPRECATED transition (Task 4.2)."""
import time
import pytest

from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    KnowledgeObject,
)
from src.knowledge.core.lifecycle import LifecycleEngine
from src.knowledge.lifecycle.decay import DecayBridge


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_obj(obj_id="ko-test", state=LifecycleState.ACTIVE, heat=50, grade="B"):
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.CONCEPT,
        title="Test Object",
        content="test content",
        lifecycle=state,
        confidence=0.8,
        provenance=Provenance(source_path="/test.md"),
        grade=grade,
        heat=heat,
        created_at=1000,
        updated_at=1000,
    )


# ===================================================================
# 1. on_heat_decayed triggers transition to DEPRECATED
# ===================================================================

class TestOnHeatDecayedTriggersTransition:
    """heat=0 + is_zombie=True → transition to DEPRECATED."""

    def test_decays_active_object(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE, heat=0)
        bridge.register_object(obj)

        result = bridge.on_heat_decayed(obj.id, 0, True)
        assert result == "deprecated"
        assert obj.lifecycle == LifecycleState.DEPRECATED

    def test_transition_is_idempotent(self):
        """Calling on_heat_decayed twice on same object is safe (no crash)."""
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        bridge.on_heat_decayed(obj.id, 0, True)
        # Second call — already DEPRECATED, should return None gracefully
        result = bridge.on_heat_decayed(obj.id, 0, True)
        assert result is None
        assert obj.lifecycle == LifecycleState.DEPRECATED


# ===================================================================
# 2. on_heat_decayed no transition if heat > 0
# ===================================================================

class TestOnHeatDecayedHeatAboveZero:
    """heat > 0 → no transition."""

    def test_heat_10_no_transition(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE, heat=10)
        bridge.register_object(obj)

        result = bridge.on_heat_decayed(obj.id, 10, True)
        assert result is None
        assert obj.lifecycle == LifecycleState.ACTIVE

    def test_heat_50_no_transition(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE, heat=50)
        bridge.register_object(obj)

        result = bridge.on_heat_decayed(obj.id, 50, True)
        assert result is None
        assert obj.lifecycle == LifecycleState.ACTIVE


# ===================================================================
# 3. on_heat_decayed no transition if not zombie
# ===================================================================

class TestOnHeatDecayedNotZombie:
    """heat=0 but is_zombie=False → no transition."""

    def test_heat_zero_not_zombie(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE, heat=0)
        bridge.register_object(obj)

        result = bridge.on_heat_decayed(obj.id, 0, False)
        assert result is None
        assert obj.lifecycle == LifecycleState.ACTIVE


# ===================================================================
# 4. on_heat_restored from DEPRECATED
# ===================================================================

class TestOnHeatRestoredFromDeprecated:
    """DEPRECATED due to heat decay + heat>0 → transition back to ACTIVE."""

    def test_restores_active(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        # First decay it
        bridge.on_heat_decayed(obj.id, 0, True)
        assert obj.lifecycle == LifecycleState.DEPRECATED

        # Then restore
        result = bridge.on_heat_restored(obj.id, 50)
        assert result == "active"
        assert obj.lifecycle == LifecycleState.ACTIVE

    def test_heat_zero_does_not_restore(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        bridge.on_heat_decayed(obj.id, 0, True)
        assert obj.lifecycle == LifecycleState.DEPRECATED

        result = bridge.on_heat_restored(obj.id, 0)
        assert result is None
        assert obj.lifecycle == LifecycleState.DEPRECATED


# ===================================================================
# 5. on_heat_restored not DEPRECATED
# ===================================================================

class TestOnHeatRestoredNotDeprecated:
    """Already ACTIVE → null transition (no-op)."""

    def test_active_object_restore_noop(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.ACTIVE, heat=50)
        bridge.register_object(obj)

        result = bridge.on_heat_restored(obj.id, 50)
        assert result is None
        assert obj.lifecycle == LifecycleState.ACTIVE

    def test_not_tracked_by_bridge(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(state=LifecycleState.DEPRECATED, heat=50)
        bridge.register_object(obj)
        # Not in _deprecated_by_heat — shouldn't transition
        result = bridge.on_heat_restored(obj.id, 50)
        assert result is None


# ===================================================================
# 6. get_deprecated_objects tracks heat-decayed objects
# ===================================================================

class TestGetDeprecatedObjects:
    """get_deprecated_objects returns IDs of objects deprecated via heat."""

    def test_tracks_deprecated_objects(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)

        objs = [
            _make_obj(obj_id="ko-a", state=LifecycleState.ACTIVE),
            _make_obj(obj_id="ko-b", state=LifecycleState.ACTIVE),
        ]
        for o in objs:
            bridge.register_object(o)

        bridge.on_heat_decayed("ko-a", 0, True)
        bridge.on_heat_decayed("ko-b", 0, True)

        deprecated = bridge.get_deprecated_objects()
        assert sorted(deprecated) == ["ko-a", "ko-b"]

    def test_restored_object_removed_from_list(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(obj_id="ko-r", state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        bridge.on_heat_decayed(obj.id, 0, True)
        assert len(bridge.get_deprecated_objects()) == 1

        bridge.on_heat_restored(obj.id, 50)
        assert len(bridge.get_deprecated_objects()) == 0

    def test_returns_empty_list_initially(self):
        bridge = DecayBridge(LifecycleEngine())
        assert bridge.get_deprecated_objects() == []


# ===================================================================
# 7. get_decay_candidates sorts correctly
# ===================================================================

class TestGetDecayCandidatesSort:
    """Lower heat + older last_used_at → higher decay priority."""

    def test_lower_heat_ranks_higher(self):
        bridge = DecayBridge(LifecycleEngine())
        objs = [
            {"id": "a", "heat": 90, "last_used_at": 1000, "grade": "B"},
            {"id": "b", "heat": 10, "last_used_at": 1000, "grade": "B"},
        ]
        result = bridge.get_decay_candidates(objs)
        assert result[0]["id"] == "b"  # lower heat first
        assert result[1]["id"] == "a"

    def test_older_last_used_ranks_higher(self):
        bridge = DecayBridge(LifecycleEngine())
        recent = int(time.time() * 1000)
        old = recent - 90 * 86400 * 1000  # 90 days ago
        objs = [
            {"id": "recent", "heat": 50, "last_used_at": recent, "grade": "B"},
            {"id": "old", "heat": 50, "last_used_at": old, "grade": "B"},
        ]
        result = bridge.get_decay_candidates(objs)
        assert result[0]["id"] == "old"  # older first

    def test_combined_factors(self):
        bridge = DecayBridge(LifecycleEngine())
        old = int(time.time() * 1000) - 30 * 86400 * 1000  # 30 days
        objs = [
            {"id": "hot_old", "heat": 80, "last_used_at": old, "grade": "B"},
            {"id": "cold_recent", "heat": 10, "last_used_at": int(time.time() * 1000), "grade": "B"},
        ]
        result = bridge.get_decay_candidates(objs)
        # Cold beats hot+old when age gap is small (heat dominates)
        # hot_old: (100-80)*1 + 30*0.5 + 10 = 45
        # cold_recent: (100-10)*1 + 0*0.5 + 10 = 100
        assert result[0]["id"] == "cold_recent"


# ===================================================================
# 8. C-grade decays faster
# ===================================================================

class TestGetDecayCandidatesGrade:
    """C-grade objects rank higher in decay priority than A-grade."""

    def test_c_grade_ranks_higher_than_a(self):
        bridge = DecayBridge(LifecycleEngine())
        objs = [
            {"id": "a_grade", "heat": 10, "last_used_at": 1000, "grade": "A"},
            {"id": "c_grade", "heat": 10, "last_used_at": 1000, "grade": "C"},
        ]
        result = bridge.get_decay_candidates(objs)
        assert result[0]["id"] == "c_grade"

    def test_b_grade_between_a_and_c(self):
        bridge = DecayBridge(LifecycleEngine())
        objs = [
            {"id": "a", "heat": 10, "last_used_at": 1000, "grade": "A"},
            {"id": "b", "heat": 10, "last_used_at": 1000, "grade": "B"},
            {"id": "c", "heat": 10, "last_used_at": 1000, "grade": "C"},
        ]
        result = bridge.get_decay_candidates(objs)
        assert result[0]["id"] == "c"
        assert result[1]["id"] == "b"
        assert result[2]["id"] == "a"


# ===================================================================
# 9. get_decay_candidates empty list
# ===================================================================

class TestGetDecayCandidatesEmpty:
    """Empty input → empty output."""

    def test_empty_list(self):
        bridge = DecayBridge(LifecycleEngine())
        result = bridge.get_decay_candidates([])
        assert result == []

    def test_single_object(self):
        bridge = DecayBridge(LifecycleEngine())
        result = bridge.get_decay_candidates([
            {"id": "solo", "heat": 50, "last_used_at": 1000, "grade": "B"},
        ])
        assert len(result) == 1
        assert result[0]["id"] == "solo"


# ===================================================================
# 10. DEPRECATED objects stay in list (not removed)
# ===================================================================

class TestDecayDoesNotAffectSearchability:
    """DEPRECATED objects remain in decay candidates — searchable, not removed."""

    def test_deprecated_object_in_candidates(self):
        bridge = DecayBridge(LifecycleEngine())
        obj = _make_obj(state=LifecycleState.ACTIVE)
        bridge.register_object(obj)
        bridge.on_heat_decayed(obj.id, 0, True)

        candidates = bridge.get_decay_candidates([
            {"id": obj.id, "heat": 0, "last_used_at": 1000, "grade": "B", "has_conflicts": False},
        ])
        assert len(candidates) == 1
        assert candidates[0]["id"] == obj.id

    def test_deprecated_objects_mixed_with_active(self):
        bridge = DecayBridge(LifecycleEngine())
        a = _make_obj(obj_id="ko-a", state=LifecycleState.ACTIVE)
        b = _make_obj(obj_id="ko-b", state=LifecycleState.ACTIVE)
        bridge.register_object(a)
        bridge.register_object(b)
        bridge.on_heat_decayed("ko-a", 0, True)

        candidates = bridge.get_decay_candidates([
            {"id": "ko-a", "heat": 0, "last_used_at": 1000, "grade": "B"},
            {"id": "ko-b", "heat": 50, "last_used_at": 1000, "grade": "B"},
        ])
        assert len(candidates) == 2  # both present, nothing removed


# ===================================================================
# 11. LifecycleEvent emitted on transition
# ===================================================================

class TestLifecycleEventEmitted:
    """DecayBridge transitions emit lifecycle.changed events via LifecycleEngine."""

    def test_decay_emits_event(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(obj_id="ko-evt", state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)
        bridge.on_heat_decayed(obj.id, 0, True)

        assert len(events) == 1
        e = events[0]
        assert e["event"] == "lifecycle.changed"
        assert e["object_id"] == "ko-evt"
        assert e["from"] == "active"
        assert e["to"] == "deprecated"
        assert e["reason"] == "heat decayed to zero"
        assert "timestamp" in e

    def test_restore_emits_event(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(obj_id="ko-rst", state=LifecycleState.ACTIVE)
        bridge.register_object(obj)

        bridge.on_heat_decayed(obj.id, 0, True)  # → DEPRECATED

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)
        bridge.on_heat_restored(obj.id, 50)

        assert len(events) == 1
        e = events[0]
        assert e["event"] == "lifecycle.changed"
        assert e["object_id"] == "ko-rst"
        assert e["from"] == "deprecated"
        assert e["to"] == "active"
        assert e["reason"] == "heat restored"

    def test_no_event_when_no_transition(self):
        engine = LifecycleEngine()
        bridge = DecayBridge(engine)
        obj = _make_obj(obj_id="ko-noevt", state=LifecycleState.ACTIVE, heat=10)
        bridge.register_object(obj)

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)
        bridge.on_heat_decayed(obj.id, 10, True)  # heat > 0 → no transition

        assert len(events) == 0


# ===================================================================
# Edge cases
# ===================================================================

class TestDecayBridgeEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_unregistered_object_is_noop(self):
        bridge = DecayBridge(LifecycleEngine())
        result = bridge.on_heat_decayed("nonexistent", 0, True)
        assert result is None

    def test_conflicts_slow_decay(self):
        """Objects with conflicts get lower decay priority (score penalty)."""
        bridge = DecayBridge(LifecycleEngine())
        objs = [
            {"id": "no_conflict", "heat": 10, "last_used_at": 1000, "grade": "B", "has_conflicts": False},
            {"id": "has_conflict", "heat": 10, "last_used_at": 1000, "grade": "B", "has_conflicts": True},
        ]
        result = bridge.get_decay_candidates(objs)
        # No-conflict object ranks higher (conflicts slow decay)
        assert result[0]["id"] == "no_conflict"
