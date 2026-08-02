"""Test MemoryType enum and KnowledgeType mapping (Task 3.1)."""
import pytest

from src.knowledge.core.object import KnowledgeType
from src.knowledge.memory.types import MemoryType, memory_type_from_knowledge_type


class TestMemoryTypeEnum:
    """MemoryType has exactly 4 values."""

    def test_all_four_values_exist(self):
        """All 4 MemoryType values are defined."""
        assert hasattr(MemoryType, "SEMANTIC")
        assert hasattr(MemoryType, "EPISODIC")
        assert hasattr(MemoryType, "DECISION")
        assert hasattr(MemoryType, "PROCEDURAL")

    def test_values_serialize_to_correct_strings(self):
        """Each MemoryType value serializes to the expected string."""
        assert MemoryType.SEMANTIC.value == "semantic"
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.DECISION.value == "decision"
        assert MemoryType.PROCEDURAL.value == "procedural"

    def test_total_count_is_four(self):
        """MemoryType has exactly 4 members."""
        members = list(MemoryType)
        assert len(members) == 4, f"Expected 4, got {len(members)}: {[m.value for m in members]}"


class TestMemoryTypeToKnowledgeType:
    """Mapping: MemoryType -> KnowledgeType."""

    def test_semantic_maps_to_concept(self):
        """SEMANTIC maps to KnowledgeType.CONCEPT."""
        assert MemoryType.SEMANTIC.to_knowledge_type() == KnowledgeType.CONCEPT

    def test_episodic_maps_to_event(self):
        """EPISODIC maps to KnowledgeType.EVENT."""
        assert MemoryType.EPISODIC.to_knowledge_type() == KnowledgeType.EVENT

    def test_decision_maps_to_decision(self):
        """DECISION maps to KnowledgeType.DECISION."""
        assert MemoryType.DECISION.to_knowledge_type() == KnowledgeType.DECISION

    def test_procedural_maps_to_procedure(self):
        """PROCEDURAL maps to KnowledgeType.PROCEDURE."""
        assert MemoryType.PROCEDURAL.to_knowledge_type() == KnowledgeType.PROCEDURE


class TestKnowledgeTypeToMemoryType:
    """Reverse mapping: KnowledgeType -> MemoryType."""

    def test_concept_maps_to_semantic(self):
        """KnowledgeType.CONCEPT reverse-maps to MemoryType.SEMANTIC."""
        assert memory_type_from_knowledge_type(KnowledgeType.CONCEPT) == MemoryType.SEMANTIC

    def test_event_maps_to_episodic(self):
        """KnowledgeType.EVENT reverse-maps to MemoryType.EPISODIC."""
        assert memory_type_from_knowledge_type(KnowledgeType.EVENT) == MemoryType.EPISODIC

    def test_decision_maps_to_decision(self):
        """KnowledgeType.DECISION reverse-maps to MemoryType.DECISION."""
        assert memory_type_from_knowledge_type(KnowledgeType.DECISION) == MemoryType.DECISION

    def test_procedure_maps_to_procedural(self):
        """KnowledgeType.PROCEDURE reverse-maps to MemoryType.PROCEDURAL."""
        assert memory_type_from_knowledge_type(KnowledgeType.PROCEDURE) == MemoryType.PROCEDURAL

    def test_unmapped_types_return_none(self):
        """KnowledgeTypes without a memory mapping return None."""
        assert memory_type_from_knowledge_type(KnowledgeType.DOCUMENT) is None
        assert memory_type_from_knowledge_type(KnowledgeType.ENTITY) is None
        assert memory_type_from_knowledge_type(KnowledgeType.CLAIM) is None
        assert memory_type_from_knowledge_type(KnowledgeType.SYNTHESIS) is None


class TestMemoryTypeCompleteness:
    """All MemoryType values are meaningfully mappable."""

    def test_all_memory_types_are_mappable(self):
        """Every MemoryType has a valid KnowledgeType (no None or missing)."""
        for mt in MemoryType:
            kt = mt.to_knowledge_type()
            assert isinstance(kt, KnowledgeType), (
                f"MemoryType.{mt.name} maps to {kt!r}, expected a KnowledgeType"
            )

    def test_round_trip_preserves_value(self):
        """MemoryType -> KnowledgeType -> MemoryType preserves the original value."""
        for mt in MemoryType:
            kt = mt.to_knowledge_type()
            back = memory_type_from_knowledge_type(kt)
            assert back == mt, (
                f"Round-trip failed: {mt} -> {kt} -> {back}"
            )
