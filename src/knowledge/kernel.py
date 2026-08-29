"""KnowledgeKernel — unified infrastructure facade for agent code.

Assembles Phase 1 subsystems (permissions, events, lifecycle, versions) into a
single entry point with consistent audit trails and permission gating.

Task 4（plan 2026-08-29-kc-integrity-idempotency-layered.md）扩展：
- ``replay_object(object_id, version=None)`` 通过 VersionManager 历史快照
  重建 KnowledgeObject；不应用 events.jsonl 中"版本之间"的事件（旧版本
  的状态由旧版快照数据给出）。
"""

from dataclasses import dataclass
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


@dataclass
class ReplayResult:
    """Result of ``KnowledgeKernel.replay_object``.

    Task 4 frozen interface: ``object_id`` + ``version`` (None = latest)
    + reconstructed ``object`` + ``reason_codes`` for diagnostics.

    ``object`` is ``None`` only when no version exists for the requested
    id (test contract: ``reason_codes == ()`` for known objects).
    """

    object_id: str
    version: int | None
    object: KnowledgeObject | None
    reason_codes: tuple[str, ...] = ()

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

    def replay_object(
        self,
        object_id: str,
        version: int | None = None,
    ) -> ReplayResult:
        """Reconstruct a KnowledgeObject from durable version snapshots.

        Task 4 §Step 3: same inputs (object_id + version) → same output.
        ``version`` is 1-based; ``None`` = latest snapshot. Events
        between snapshots are NOT applied — replay returns the state at
        the chosen version as it was when the snapshot was written
        (the events.jsonl stream is for audit, not for state machine
        replay).

        Args:
            object_id: The KnowledgeObject id to reconstruct.
            version: 1-based version number, or ``None`` for latest.

        Returns:
            ``ReplayResult`` carrying the reconstructed object and
            ``reason_codes`` (empty on success; ``("unknown_object_id",)``
            when no version exists).
        """
        history = self.versions.get_history(object_id)
        if not history:
            return ReplayResult(
                object_id=object_id,
                version=None,
                object=None,
                reason_codes=("unknown_object_id",),
            )
        if version is None:
            vref = history[-1]
        else:
            if version < 1 or version > len(history):
                return ReplayResult(
                    object_id=object_id,
                    version=version,
                    object=None,
                    reason_codes=("unknown_object_id",),
                )
            vref = history[version - 1]
        data = self.versions._load_version_data(object_id, vref.version_id)  # noqa: SLF001
        # Lazy import to avoid a circular import (version_manager ↔ object).
        from src.knowledge.core.version_manager import _deserialize_object
        obj = _deserialize_object(data)
        return ReplayResult(
            object_id=object_id,
            version=version if version is not None else len(history),
            object=obj,
            reason_codes=(),
        )


# ---------------------------------------------------------------------------
# Per-project singleton
# ---------------------------------------------------------------------------

#: Per-project kernels keyed by normalized root path (Finding I-1: final
#: whole-branch review — a single global instance made
#: ``get_kernel(root_a) is get_kernel(root_b)``, leaking state across
#: projects). The same normalized root always maps to the same instance;
#: different roots map to different instances.
_kernel_instances: dict[str, KnowledgeKernel] = {}

#: Active/default kernel — the instance most recently returned by a
#: ``get_kernel(project_path)`` call. Kept as a module attribute under
#: its historical name so ``get_kernel(None)`` (and the existing tests
#: that reset it to ``None``) keep working: after initialisation,
#: ``get_kernel(None)`` returns the existing kernel for that project,
#: never a cross-project kernel.
_kernel_instance: KnowledgeKernel | None = None


def _normalize_root(project_path: Path) -> str:
    """Return a stable, normalized registry key for *project_path*."""
    return str(Path(project_path).resolve())


def get_kernel(project_path: Path | None = None) -> KnowledgeKernel:
    """Return the per-project KnowledgeKernel singleton.

    Each distinct normalized *project_path* gets its own kernel (Finding
    I-1: per-project isolation). The first call must include
    *project_path* to initialise a kernel; the same root always returns
    the same instance and different roots return different instances.
    Subsequent calls with ``None`` return the active kernel — the one
    most recently created via a *project_path* call — so a project that
    has already been initialised can be re-acquired without repeating
    the path.

    Raises ``RuntimeError`` if called without *project_path* before any
    kernel has been initialised.
    """
    global _kernel_instance
    if project_path is None:
        if _kernel_instance is None:
            raise RuntimeError(
                "KnowledgeKernel not initialised — call get_kernel(project_path) first"
            )
        return _kernel_instance
    root = _normalize_root(project_path)
    kernel = _kernel_instances.get(root)
    if kernel is None:
        kernel = KnowledgeKernel(Path(root))
        _kernel_instances[root] = kernel
    _kernel_instance = kernel
    return kernel
