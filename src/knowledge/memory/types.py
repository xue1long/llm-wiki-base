"""Memory types for the knowledge OS memory system.

Each memory type maps to a KnowledgeType for storage as KnowledgeObjects.
"""
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge.core.object import KnowledgeType


class MemoryType(str, Enum):
    """Memory types for the knowledge OS memory system.

    Each memory type maps to a KnowledgeType for storage as KnowledgeObjects.
    """

    SEMANTIC = "semantic"       # 事实/知识 → KnowledgeType.CONCEPT
    EPISODIC = "episodic"       # 事件/经历 → KnowledgeType.EVENT
    DECISION = "decision"       # 选择+理由 → KnowledgeType.DECISION
    PROCEDURAL = "procedural"   # 操作流程 → KnowledgeType.PROCEDURE

    def to_knowledge_type(self) -> "KnowledgeType":
        """Map this MemoryType to the corresponding KnowledgeType."""
        from src.knowledge.core.object import KnowledgeType

        _MAP: dict["MemoryType", "KnowledgeType"] = {
            MemoryType.SEMANTIC: KnowledgeType.CONCEPT,
            MemoryType.EPISODIC: KnowledgeType.EVENT,
            MemoryType.DECISION: KnowledgeType.DECISION,
            MemoryType.PROCEDURAL: KnowledgeType.PROCEDURE,
        }
        return _MAP[self]


def memory_type_from_knowledge_type(kt: "KnowledgeType") -> MemoryType | None:
    """Reverse map: KnowledgeType -> MemoryType. Returns None if no memory mapping exists."""
    from src.knowledge.core.object import KnowledgeType

    _REVERSE_MAP: dict["KnowledgeType", MemoryType] = {
        KnowledgeType.CONCEPT: MemoryType.SEMANTIC,
        KnowledgeType.EVENT: MemoryType.EPISODIC,
        KnowledgeType.DECISION: MemoryType.DECISION,
        KnowledgeType.PROCEDURE: MemoryType.PROCEDURAL,
    }
    return _REVERSE_MAP.get(kt)
