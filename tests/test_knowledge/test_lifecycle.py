"""Test LifecycleEngine — 8-state 15-edge state machine (Task 1.5)."""
import time
import pytest

from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    KnowledgeObject,
)
from src.knowledge.core.lifecycle import LifecycleEngine, task_status_to_lifecycle


# ---------------------------------------------------------------------------
# Helper: build a minimal KnowledgeObject for lifecycle tests
# ---------------------------------------------------------------------------

def _make_obj(obj_id="ko-test", state=LifecycleState.CREATED):
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.CONCEPT,
        title="Test Object",
        content="test content",
        lifecycle=state,
        confidence=0.8,
        provenance=Provenance(source_path="/test.md"),
        created_at=1000,
        updated_at=1000,
    )


# ---------------------------------------------------------------------------
# Valid transition set (15 edges)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS = {
    (LifecycleState.CREATED, LifecycleState.PROCESSING),
    (LifecycleState.CREATED, LifecycleState.ARCHIVED),
    (LifecycleState.PROCESSING, LifecycleState.REVIEWING),
    (LifecycleState.PROCESSING, LifecycleState.FAILED),
    (LifecycleState.PROCESSING, LifecycleState.ARCHIVED),
    (LifecycleState.REVIEWING, LifecycleState.ACTIVE),
    (LifecycleState.REVIEWING, LifecycleState.REJECTED),
    (LifecycleState.REVIEWING, LifecycleState.PROCESSING),
    (LifecycleState.ACTIVE, LifecycleState.DEPRECATED),
    (LifecycleState.ACTIVE, LifecycleState.ARCHIVED),
    (LifecycleState.DEPRECATED, LifecycleState.ACTIVE),
    (LifecycleState.DEPRECATED, LifecycleState.ARCHIVED),
    (LifecycleState.FAILED, LifecycleState.PROCESSING),
    (LifecycleState.FAILED, LifecycleState.ARCHIVED),
    (LifecycleState.REJECTED, LifecycleState.ARCHIVED),
}


# ===================================================================
# Test 1: can_transition returns True for all 15 valid transitions
# ===================================================================

class TestCanTransitionValid:
    """can_transition returns True for every valid transition."""

    @pytest.mark.parametrize("prev_state, next_state", sorted(VALID_TRANSITIONS, key=str))
    def test_valid_transition(self, prev_state, next_state):
        engine = LifecycleEngine()
        assert engine.can_transition(prev_state, next_state) is True, (
            f"Expected {prev_state.value} → {next_state.value} to be valid"
        )

    def test_total_valid_transitions_is_15(self):
        """Sanity check: exactly 15 valid edges."""
        assert len(VALID_TRANSITIONS) == 15, (
            f"Expected 15 valid transitions, got {len(VALID_TRANSITIONS)}"
        )


# ===================================================================
# Test 2: can_transition returns False for invalid transitions
# ===================================================================

class TestCanTransitionInvalid:
    """can_transition returns False for disallowed transitions."""

    def test_created_to_active_is_invalid(self):
        engine = LifecycleEngine()
        assert engine.can_transition(LifecycleState.CREATED, LifecycleState.ACTIVE) is False

    def test_created_to_reviewing_is_invalid(self):
        engine = LifecycleEngine()
        assert engine.can_transition(LifecycleState.CREATED, LifecycleState.REVIEWING) is False

    def test_processing_to_active_is_invalid(self):
        engine = LifecycleEngine()
        assert engine.can_transition(LifecycleState.PROCESSING, LifecycleState.ACTIVE) is False

    def test_active_to_created_is_invalid(self):
        engine = LifecycleEngine()
        assert engine.can_transition(LifecycleState.ACTIVE, LifecycleState.CREATED) is False

    def test_same_state_is_invalid(self):
        """Self-transition is not allowed (no change)."""
        engine = LifecycleEngine()
        for state in LifecycleState:
            assert engine.can_transition(state, state) is False, (
                f"Self-transition {state.value} → {state.value} should be invalid"
            )

    def test_archived_to_anything_is_invalid(self):
        """ARCHIVED is terminal — no outbound transitions."""
        engine = LifecycleEngine()
        for state in LifecycleState:
            if state == LifecycleState.ARCHIVED:
                continue
            assert engine.can_transition(LifecycleState.ARCHIVED, state) is False, (
                f"ARCHIVED → {state.value} should be invalid"
            )


# ===================================================================
# Test 3: transition updates lifecycle and updated_at
# ===================================================================

class TestTransitionUpdatesObject:
    """transition() mutates the KnowledgeObject in-place."""

    def test_lifecycle_is_updated(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED)

        result = engine.transition(obj, LifecycleState.PROCESSING, "start processing")
        assert result.lifecycle == LifecycleState.PROCESSING
        assert obj.lifecycle == LifecycleState.PROCESSING  # in-place

    def test_updated_at_is_bumped(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED, obj_id="ko-ts")
        original_updated_at = obj.updated_at

        time.sleep(0.01)  # ensure timestamp changes
        result = engine.transition(obj, LifecycleState.PROCESSING, "processing")

        assert result.updated_at > original_updated_at, (
            f"updated_at {result.updated_at} should be > {original_updated_at}"
        )

    def test_returns_same_object_reference(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED)

        result = engine.transition(obj, LifecycleState.PROCESSING, "go")
        assert result is obj

    def test_other_fields_are_preserved(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.REVIEWING, obj_id="ko-preserve")

        result = engine.transition(obj, LifecycleState.ACTIVE, "approved")
        assert result.id == "ko-preserve"
        assert result.type == KnowledgeType.CONCEPT
        assert result.title == "Test Object"
        assert result.content == "test content"
        assert result.confidence == 0.8
        assert result.created_at == 1000


# ===================================================================
# Test 4: transition raises ValueError for illegal transitions
# ===================================================================

class TestTransitionRaisesOnIllegal:
    """transition() raises ValueError when the transition is not allowed."""

    def test_created_to_active_raises(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED)

        with pytest.raises(ValueError, match="Illegal transition"):
            engine.transition(obj, LifecycleState.ACTIVE, "skip ahead")

    def test_archived_to_anything_raises(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.ARCHIVED)

        for state in LifecycleState:
            if state == LifecycleState.ARCHIVED:
                continue
            with pytest.raises(ValueError, match="Illegal transition"):
                engine.transition(obj, state, f"try {state.value}")

    def test_self_transition_raises(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.ACTIVE)

        with pytest.raises(ValueError, match="Illegal transition"):
            engine.transition(obj, LifecycleState.ACTIVE, "no-op")

    def test_error_message_includes_states_and_reason(self):
        """Error message should contain the from/to states and the reason."""
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED)

        with pytest.raises(ValueError) as exc_info:
            engine.transition(obj, LifecycleState.ACTIVE, "test-reason-xyz")
        msg = str(exc_info.value)
        assert "created" in msg.lower()
        assert "active" in msg.lower()
        assert "test-reason-xyz" in msg


# ===================================================================
# Test 5: transition emits event to EventBus
# ===================================================================

class TestTransitionEmitsEvent:
    """transition() emits a LifecycleEvent to the EventBus."""

    def test_event_is_emitted_on_valid_transition(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED, obj_id="ko-event")

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)
        engine.transition(obj, LifecycleState.PROCESSING, "start")

        assert len(events) == 1
        e = events[0]
        assert e["event"] == "lifecycle.changed"
        assert e["object_id"] == "ko-event"
        assert e["from"] == "created"
        assert e["to"] == "processing"
        assert e["reason"] == "start"
        assert "timestamp" in e

    def test_no_event_on_illegal_transition(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED, obj_id="ko-noevt")

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)

        with pytest.raises(ValueError):
            engine.transition(obj, LifecycleState.ACTIVE, "bad")

        assert len(events) == 0

    def test_multiple_transitions_emit_sequence(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.CREATED, obj_id="ko-seq")

        events = []

        def handler(payload):
            events.append(payload)

        engine.event_bus.on("lifecycle.changed", handler)

        # CREATED → PROCESSING → REVIEWING → ACTIVE
        engine.transition(obj, LifecycleState.PROCESSING, "step 1")
        engine.transition(obj, LifecycleState.REVIEWING, "step 2")
        engine.transition(obj, LifecycleState.ACTIVE, "step 3")

        assert len(events) == 3
        assert events[0]["from"] == "created"
        assert events[0]["to"] == "processing"
        assert events[1]["from"] == "processing"
        assert events[1]["to"] == "reviewing"
        assert events[2]["from"] == "reviewing"
        assert events[2]["to"] == "active"


# ===================================================================
# Test 6: task_status_to_lifecycle mapping
# ===================================================================

class TestTaskStatusToLifecycle:
    """task_status_to_lifecycle maps Queue task statuses to LifecycleState."""

    def test_pending_returns_none(self):
        assert task_status_to_lifecycle("PENDING") is None

    def test_running_maps_to_processing(self):
        assert task_status_to_lifecycle("RUNNING") == LifecycleState.PROCESSING

    def test_waiting_review_maps_to_reviewing(self):
        assert task_status_to_lifecycle("WAITING_REVIEW") == LifecycleState.REVIEWING

    def test_approved_maps_to_active(self):
        assert task_status_to_lifecycle("APPROVED") == LifecycleState.ACTIVE

    def test_rejected_maps_to_rejected(self):
        assert task_status_to_lifecycle("REJECTED") == LifecycleState.REJECTED

    def test_failed_maps_to_failed(self):
        assert task_status_to_lifecycle("FAILED") == LifecycleState.FAILED

    def test_archived_maps_to_archived(self):
        assert task_status_to_lifecycle("ARCHIVED") == LifecycleState.ARCHIVED

    def test_timeout_maps_to_archived(self):
        assert task_status_to_lifecycle("TIMEOUT") == LifecycleState.ARCHIVED

    def test_dead_letter_maps_to_failed(self):
        assert task_status_to_lifecycle("DEAD_LETTER") == LifecycleState.FAILED

    def test_unknown_status_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown task status"):
            task_status_to_lifecycle("NONEXISTENT")

    def test_all_known_statuses_are_mapped(self):
        known = {"PENDING", "RUNNING", "WAITING_REVIEW", "APPROVED",
                 "REJECTED", "FAILED", "ARCHIVED", "TIMEOUT", "DEAD_LETTER"}
        for status in known:
            result = task_status_to_lifecycle(status)
            if status == "PENDING":
                assert result is None
            else:
                assert isinstance(result, LifecycleState), (
                    f"task_status_to_lifecycle({status!r}) should return LifecycleState, got {result!r}"
                )


# ===================================================================
# Test 7: ARCHIVED is terminal
# ===================================================================

class TestArchivedIsTerminal:
    """ARCHIVED state has no outbound transitions."""

    def test_can_transition_false_for_all_outbound(self):
        engine = LifecycleEngine()
        for state in LifecycleState:
            assert engine.can_transition(LifecycleState.ARCHIVED, state) is False, (
                f"ARCHIVED → {state.value} should be False"
            )

    def test_transition_raises_for_all_outbound(self):
        engine = LifecycleEngine()
        obj = _make_obj(state=LifecycleState.ARCHIVED, obj_id="ko-dead")
        for state in LifecycleState:
            with pytest.raises(ValueError, match="Illegal transition"):
                engine.transition(obj, state, "resurrect")

    def test_archived_to_archived_also_raises(self):
        """Even self-transition is disallowed for ARCHIVED."""
        engine = LifecycleEngine()
        # use a valid path to get to ARCHIVED first
        obj = _make_obj(state=LifecycleState.CREATED)
        engine.transition(obj, LifecycleState.ARCHIVED, "archive")

        with pytest.raises(ValueError, match="Illegal transition"):
            engine.transition(obj, LifecycleState.ARCHIVED, "re-archive")


# ===================================================================
# Test: LifecycleEngine accepts custom EventBus
# ===================================================================

class TestCustomEventBus:
    """LifecycleEngine can use a custom EventBus instance."""

    def test_custom_event_bus_is_used(self):
        from src.events.event_bus import EventBus
        custom_bus = EventBus()
        engine = LifecycleEngine(event_bus=custom_bus)
        assert engine.event_bus is custom_bus

    def test_custom_event_bus_receives_events(self):
        from src.events.event_bus import EventBus
        custom_bus = EventBus()
        engine = LifecycleEngine(event_bus=custom_bus)
        obj = _make_obj(state=LifecycleState.CREATED, obj_id="ko-custom")

        events = []

        def handler(payload):
            events.append(payload)

        custom_bus.on("lifecycle.changed", handler)
        engine.transition(obj, LifecycleState.PROCESSING, "custom bus test")

        assert len(events) == 1
        assert events[0]["object_id"] == "ko-custom"
