"""Tests for KnowledgeKernel — unified infrastructure facade (Task 1.12)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.knowledge.kernel import (
    KnowledgeKernel,
    get_kernel,
    PermissionEngine,
    KNOWLEDGE_CREATE,
    KNOWLEDGE_UPDATE,
)
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.permissions import AgentType
from src.events.event_bus import EventBus
from src.knowledge.core.lifecycle import LifecycleEngine
from src.knowledge.core.version_manager import VersionManager


@pytest.fixture
def sample_object():
    return KnowledgeObject(
        id="test-001",
        type=KnowledgeType.CONCEPT,
        title="Test Concept",
        content="Some content",
        lifecycle=LifecycleState.CREATED,
        confidence=0.9,
        provenance=Provenance(source_path=""),
    )


@pytest.fixture
def kernel(tmp_path):
    """Create a kernel with a temporary project path."""
    return KnowledgeKernel(tmp_path)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestKnowledgeKernelInit:
    def test_initializes_all_subsystems(self, kernel):
        """Kernel should have permissions, events, lifecycle, versions."""
        assert isinstance(kernel.permissions, PermissionEngine)
        assert isinstance(kernel.events, EventBus)
        assert isinstance(kernel.lifecycle, LifecycleEngine)
        assert isinstance(kernel.versions, VersionManager)

    def test_uses_global_event_bus_singleton(self, kernel):
        """Kernel.events must be the module-level singleton, not a private instance."""
        from src.events.event_bus import event_bus as _global
        assert kernel.events is _global

    def test_lifecycle_engine_shares_kernel_event_bus(self, kernel):
        """LifecycleEngine should use the kernel's EventBus instance."""
        assert kernel.lifecycle.event_bus is kernel.events

    def test_extensions_dict_empty_initially(self, kernel):
        """_extensions should be an empty dict for Phase 2/3/4 registration."""
        assert kernel._extensions == {}


# ---------------------------------------------------------------------------
# create_object
# ---------------------------------------------------------------------------


class TestCreateObject:
    def test_checks_permission_and_emits_event(self, kernel, sample_object):
        with patch.object(kernel.permissions, "check", return_value=True) as mock_check, \
             patch.object(kernel.events, "emit") as mock_emit:
            result = kernel.create_object(sample_object, AgentType.PROCESSOR)

            mock_check.assert_called_once_with(AgentType.PROCESSOR, KNOWLEDGE_CREATE)
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "knowledge.created"
            assert call_args[0][1]["object"] is sample_object
            assert call_args[0][1]["agent"] == AgentType.PROCESSOR
            assert result is sample_object

    def test_denied_for_agent_without_create_permission(self, kernel, sample_object):
        """COLLECTOR has no KNOWLEDGE_CREATE permission."""
        with pytest.raises(PermissionError, match="knowledge:create"):
            kernel.create_object(sample_object, AgentType.COLLECTOR)

    def test_orchestrator_always_passes(self, kernel, sample_object):
        """ORCHESTRATOR has full permissions."""
        with patch.object(kernel.events, "emit"):
            result = kernel.create_object(sample_object, AgentType.ORCHESTRATOR)
            assert result is sample_object


# ---------------------------------------------------------------------------
# update_object
# ---------------------------------------------------------------------------


class TestUpdateObject:
    def test_snapshots_before_applying_changes(self, kernel, sample_object):
        kernel.permissions.check = MagicMock(return_value=True)
        with patch.object(kernel.versions, "snapshot") as mock_snapshot, \
             patch.object(kernel.events, "emit") as mock_emit:

            changes = {"title": "Updated Title"}
            result = kernel.update_object(sample_object, AgentType.PROCESSOR, changes)

            mock_snapshot.assert_called_once_with(sample_object)
            assert sample_object.title == "Updated Title"
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "knowledge.updated"
            assert call_args[0][1]["changes"] == changes
            assert result is sample_object

    def test_emits_version_ref_in_event(self, kernel, sample_object):
        """The 'knowledge.updated' event payload must include the version ref."""
        kernel.permissions.check = MagicMock(return_value=True)
        from src.knowledge.core.object import VersionRef
        fake_ref = VersionRef(version_id="v_99", timestamp=99)
        with patch.object(kernel.versions, "snapshot", return_value=fake_ref), \
             patch.object(kernel.events, "emit") as mock_emit:

            kernel.update_object(sample_object, AgentType.PROCESSOR, {"content": "new"})

            call_args = mock_emit.call_args
            assert call_args[0][1]["version"] is fake_ref

    def test_denied_for_agent_without_update_permission(self, kernel, sample_object):
        """COLLECTOR has no KNOWLEDGE_UPDATE permission."""
        with pytest.raises(PermissionError, match="knowledge:update"):
            kernel.update_object(sample_object, AgentType.COLLECTOR, {"title": "X"})


# ---------------------------------------------------------------------------
# transition_lifecycle
# ---------------------------------------------------------------------------


class TestTransitionLifecycle:
    def test_delegates_to_lifecycle_engine(self, kernel, sample_object):
        kernel.permissions.check = MagicMock(return_value=True)
        with patch.object(kernel.lifecycle, "transition", return_value=sample_object) as mock_transition:

            result = kernel.transition_lifecycle(
                sample_object, LifecycleState.PROCESSING, AgentType.PROCESSOR, "review started"
            )

            mock_transition.assert_called_once_with(
                sample_object, LifecycleState.PROCESSING, "review started"
            )

    def test_denied_for_agent_without_update_permission(self, kernel, sample_object):
        """COLLECTOR cannot trigger lifecycle transitions."""
        with pytest.raises(PermissionError, match="knowledge:update"):
            kernel.transition_lifecycle(
                sample_object, LifecycleState.PROCESSING, AgentType.COLLECTOR, "nope"
            )


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    def test_delegates_to_version_manager(self, kernel):
        with patch.object(kernel.versions, "get_history", return_value=[]) as mock_history:
            result = kernel.get_history("test-001")
            mock_history.assert_called_once_with("test-001")
            assert result == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestGetKernel:
    def test_returns_same_instance(self, tmp_path):
        import src.knowledge.kernel as km
        km._kernel_instance = None
        try:
            k1 = get_kernel(tmp_path)
            k2 = get_kernel()
            assert k1 is k2
        finally:
            km._kernel_instance = None

    def test_raises_when_no_instance_and_no_path(self):
        import src.knowledge.kernel as km
        km._kernel_instance = None
        try:
            with pytest.raises(RuntimeError, match="not initiali"):
                get_kernel(None)
        finally:
            km._kernel_instance = None
