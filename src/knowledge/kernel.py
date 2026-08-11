"""KnowledgeKernel — unified infrastructure facade for agent code.

Assembles Phase 1 subsystems (permissions, events, lifecycle, versions) into a
single entry point with consistent audit trails and permission gating.
"""

from pathlib import Path

from src.events.event_bus import event_bus
from src.knowledge.core.lifecycle import LifecycleEngine
from src.knowledge.core.object import (
    KnowledgeObject,
    LifecycleState,
    VersionRef,
)
from src.knowledge.core.version_manager import VersionManager
from src.permissions import AgentType

# ---------------------------------------------------------------------------
# Knowledge-specific permission constants
# ---------------------------------------------------------------------------

KNOWLEDGE_CREATE = "knowledge:create"
KNOWLEDGE_UPDATE = "knowledge:update"
RAW_CREATE = "raw:create"
RAW_READ = "raw:read"

# ---------------------------------------------------------------------------
# PermissionEngine — thin wrapper over src.permissions agent model
# ---------------------------------------------------------------------------

_AGENT_KNOWLEDGE_PERMISSIONS: dict[AgentType, set[str]] = {
    AgentType.ORCHESTRATOR: {KNOWLEDGE_CREATE, KNOWLEDGE_UPDATE},
    AgentType.PROCESSOR:    {KNOWLEDGE_CREATE, KNOWLEDGE_UPDATE},
    AgentType.LIBRARIAN:    {KNOWLEDGE_CREATE, KNOWLEDGE_UPDATE},
    AgentType.SEARCHER:     set(),
    AgentType.COLLECTOR:    {RAW_CREATE, RAW_READ},
}


class PermissionEngine:
    """Permission engine for knowledge operations.

    Wraps the agent model from ``src.permissions`` and applies it to
    knowledge-domain operations (create, update) rather than file-system paths.
    """

    def check(self, agent: AgentType, permission: str) -> bool:
        """Return True if *agent* holds *permission*."""
        allowed = _AGENT_KNOWLEDGE_PERMISSIONS.get(agent, set())
        return permission in allowed


# ---------------------------------------------------------------------------
# KnowledgeKernel
# ---------------------------------------------------------------------------

class KnowledgeKernel:
    """Unified entry point for knowledge infrastructure.

    Agents interact with knowledge through this facade rather than
    directly depending on individual subsystems. This provides
    consistent audit trails and permission gating.
    """

    def __init__(self, project_path: Path) -> None:
        self.permissions = PermissionEngine()
        self.events = event_bus
        self.lifecycle = LifecycleEngine(self.events)
        self.versions = VersionManager(project_path)
        self._extensions: dict = {}  # Phase 2 adds Graph, Phase 3 adds Memory

    # ------------------------------------------------------------------
    # Agent operation entry points
    # ------------------------------------------------------------------

    def create_object(
        self, obj: KnowledgeObject, agent: AgentType
    ) -> KnowledgeObject:
        """Register a new knowledge object.

        Raises ``PermissionError`` if *agent* lacks KNOWLEDGE_CREATE.
        """
        if not self.permissions.check(agent, KNOWLEDGE_CREATE):
            raise PermissionError(
                f"Agent {agent.value} does not have {KNOWLEDGE_CREATE} permission"
            )
        self.events.emit("knowledge.created", {"object": obj, "agent": agent})
        return obj

    def update_object(
        self, obj: KnowledgeObject, agent: AgentType, changes: dict
    ) -> KnowledgeObject:
        """Apply *changes* to *obj*, with snapshot and audit trail.

        Raises ``PermissionError`` if *agent* lacks KNOWLEDGE_UPDATE.
        """
        if not self.permissions.check(agent, KNOWLEDGE_UPDATE):
            raise PermissionError(
                f"Agent {agent.value} does not have {KNOWLEDGE_UPDATE} permission"
            )

        version_ref = self.versions.snapshot(obj)

        for key, value in changes.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

        self.events.emit("knowledge.updated", {
            "object": obj,
            "agent": agent,
            "changes": changes,
            "version": version_ref,
        })
        return obj

    def transition_lifecycle(
        self,
        obj: KnowledgeObject,
        target: LifecycleState,
        agent: AgentType,
        reason: str,
    ) -> KnowledgeObject:
        """Transition *obj* to *target* lifecycle state.

        Raises ``PermissionError`` if *agent* lacks KNOWLEDGE_UPDATE,
        or ``ValueError`` from LifecycleEngine for illegal transitions.
        """
        if not self.permissions.check(agent, KNOWLEDGE_UPDATE):
            raise PermissionError(
                f"Agent {agent.value} does not have {KNOWLEDGE_UPDATE} permission"
            )
        return self.lifecycle.transition(obj, target, reason)

    def get_history(self, object_id: str) -> list[VersionRef]:
        """Return all version snapshots for *object_id*."""
        return self.versions.get_history(object_id)


# ---------------------------------------------------------------------------
# Per-project singleton
# ---------------------------------------------------------------------------

_kernel_instance: KnowledgeKernel | None = None


def get_kernel(project_path: Path | None = None) -> KnowledgeKernel:
    """Return the per-project KnowledgeKernel singleton.

    The first call must include *project_path* to initialise the kernel.
    Subsequent calls with ``None`` return the same instance.

    Raises ``RuntimeError`` if called without *project_path* before
    initialisation.
    """
    global _kernel_instance
    if _kernel_instance is None:
        if project_path is None:
            raise RuntimeError(
                "KnowledgeKernel not initialised — call get_kernel(project_path) first"
            )
        _kernel_instance = KnowledgeKernel(project_path)
    return _kernel_instance
