"""Test KnowledgeObject core data model (Task 1.2)."""
import pytest

from src.knowledge.core.object import (
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
    KnowledgeObject,
)


class TestKnowledgeTypeEnum:
    """KnowledgeType has exactly 8 values, 1:1 with extended PageType."""

    def test_all_eight_values_exist(self):
        """All 8 KnowledgeType values are defined."""
        assert hasattr(KnowledgeType, "DOCUMENT")
        assert hasattr(KnowledgeType, "ENTITY")
        assert hasattr(KnowledgeType, "CONCEPT")
        assert hasattr(KnowledgeType, "CLAIM")
        assert hasattr(KnowledgeType, "DECISION")
        assert hasattr(KnowledgeType, "PROCEDURE")
        assert hasattr(KnowledgeType, "EVENT")
        assert hasattr(KnowledgeType, "SYNTHESIS")

    def test_values_serialize_to_correct_strings(self):
        """Each KnowledgeType value serializes to the expected string."""
        assert KnowledgeType.DOCUMENT.value == "document"
        assert KnowledgeType.ENTITY.value == "entity"
        assert KnowledgeType.CONCEPT.value == "concept"
        assert KnowledgeType.CLAIM.value == "claim"
        assert KnowledgeType.DECISION.value == "decision"
        assert KnowledgeType.PROCEDURE.value == "procedure"
        assert KnowledgeType.EVENT.value == "event"
        assert KnowledgeType.SYNTHESIS.value == "synthesis"

    def test_values_deserialize_from_strings(self):
        """Each string deserializes to the correct KnowledgeType."""
        assert KnowledgeType("document") == KnowledgeType.DOCUMENT
        assert KnowledgeType("entity") == KnowledgeType.ENTITY
        assert KnowledgeType("concept") == KnowledgeType.CONCEPT
        assert KnowledgeType("claim") == KnowledgeType.CLAIM
        assert KnowledgeType("decision") == KnowledgeType.DECISION
        assert KnowledgeType("procedure") == KnowledgeType.PROCEDURE
        assert KnowledgeType("event") == KnowledgeType.EVENT
        assert KnowledgeType("synthesis") == KnowledgeType.SYNTHESIS

    def test_total_count_is_eight(self):
        """KnowledgeType has exactly 8 members."""
        members = list(KnowledgeType)
        assert len(members) == 8, f"Expected 8, got {len(members)}: {[m.value for m in members]}"


class TestLifecycleStateEnum:
    """LifecycleState has exactly 8 values."""

    def test_all_eight_states_exist(self):
        """All 8 LifecycleState values are defined."""
        assert hasattr(LifecycleState, "CREATED")
        assert hasattr(LifecycleState, "PROCESSING")
        assert hasattr(LifecycleState, "REVIEWING")
        assert hasattr(LifecycleState, "ACTIVE")
        assert hasattr(LifecycleState, "DEPRECATED")
        assert hasattr(LifecycleState, "ARCHIVED")
        assert hasattr(LifecycleState, "FAILED")
        assert hasattr(LifecycleState, "REJECTED")

    def test_values_serialize_correctly(self):
        """Each LifecycleState value serializes to the expected lowercase string."""
        assert LifecycleState.CREATED.value == "created"
        assert LifecycleState.PROCESSING.value == "processing"
        assert LifecycleState.REVIEWING.value == "reviewing"
        assert LifecycleState.ACTIVE.value == "active"
        assert LifecycleState.DEPRECATED.value == "deprecated"
        assert LifecycleState.ARCHIVED.value == "archived"
        assert LifecycleState.FAILED.value == "failed"
        assert LifecycleState.REJECTED.value == "rejected"

    def test_total_count_is_eight(self):
        """LifecycleState has exactly 8 members."""
        members = list(LifecycleState)
        assert len(members) == 8, f"Expected 8, got {len(members)}: {[m.value for m in members]}"


class TestProvenanceCreation:
    """Provenance dataclass creation and default values."""

    def test_create_with_required_fields_only(self):
        """Provenance can be created with only source_path."""
        p = Provenance(source_path="/docs/example.md")
        assert p.source_path == "/docs/example.md"

    def test_default_values_are_correct(self):
        """Provenance defaults: page=None, quote="", ingested_at=0, ingestor_version=""."""
        p = Provenance(source_path="/x.pdf")
        assert p.page is None
        assert p.quote == ""
        assert p.ingested_at == 0
        assert p.ingestor_version == ""

    def test_create_with_all_fields(self):
        """Provenance accepts all optional fields."""
        p = Provenance(
            source_path="/doc.pdf",
            page=3,
            quote="the quick brown fox",
            ingested_at=1722556800000,
            ingestor_version="2.0.0",
        )
        assert p.source_path == "/doc.pdf"
        assert p.page == 3
        assert p.quote == "the quick brown fox"
        assert p.ingested_at == 1722556800000
        assert p.ingestor_version == "2.0.0"


class TestVersionRefCreation:
    """VersionRef dataclass creation and default values."""

    def test_create_with_required_fields(self):
        """VersionRef can be created with version_id and timestamp."""
        v = VersionRef(version_id="v1", timestamp=1722556800000)
        assert v.version_id == "v1"
        assert v.timestamp == 1722556800000

    def test_default_change_description_is_empty(self):
        """VersionRef.change_description defaults to empty string."""
        v = VersionRef(version_id="abc", timestamp=1000)
        assert v.change_description == ""

    def test_create_with_all_fields(self):
        """VersionRef accepts change_description."""
        v = VersionRef(
            version_id="v2",
            timestamp=1722556800000,
            change_description="Added lifecycle field",
        )
        assert v.version_id == "v2"
        assert v.timestamp == 1722556800000
        assert v.change_description == "Added lifecycle field"


class TestKnowledgeObjectCreation:
    """KnowledgeObject dataclass creation and default values."""

    def test_create_mandatory_fields(self):
        """KnowledgeObject can be created with minimal required fields."""
        obj = KnowledgeObject(
            id="ko-001",
            type=KnowledgeType.ENTITY,
            title="Test Entity",
            content="Some content.",
            lifecycle=LifecycleState.CREATED,
            confidence=0.85,
            grade="B",
            heat=50,
            provenance=Provenance(source_path="/test.md"),
            relations=[],
            versions=[],
            created_at=1722556800000,
            updated_at=1722556800000,
        )
        assert obj.id == "ko-001"
        assert obj.type == KnowledgeType.ENTITY
        assert obj.title == "Test Entity"
        assert obj.content == "Some content."
        assert obj.lifecycle == LifecycleState.CREATED
        assert obj.confidence == 0.85
        assert obj.grade == "B"
        assert obj.heat == 50
        assert isinstance(obj.provenance, Provenance)
        assert obj.provenance.source_path == "/test.md"
        assert obj.relations == []
        assert obj.versions == []
        assert obj.created_at == 1722556800000
        assert obj.updated_at == 1722556800000

    def test_default_values_are_correct(self):
        """KnowledgeObject default values match spec."""
        obj = KnowledgeObject(
            id="ko-002",
            type=KnowledgeType.CONCEPT,
            title="Minimal",
            content="content",
            lifecycle=LifecycleState.CREATED,
            confidence=0.5,
            provenance=Provenance(source_path="/s.md"),
        )
        assert obj.grade == "B", "Grade should default to B"
        assert obj.heat == 50, "Heat should default to 50"
        assert obj.relations == [], "Relations should default to empty list"
        assert obj.versions == [], "Versions should default to empty list"
        assert obj.created_at == 0, "created_at should default to 0"
        assert obj.updated_at == 0, "updated_at should default to 0"

    def test_confidence_clamping_not_forced(self):
        """KnowledgeObject accepts any float confidence (no clamping in dataclass)."""
        obj = KnowledgeObject(
            id="low", type=KnowledgeType.CLAIM, title="L",
            content="c", lifecycle=LifecycleState.CREATED,
            confidence=0.0, provenance=Provenance(source_path="/x"),
        )
        assert obj.confidence == 0.0

        obj2 = KnowledgeObject(
            id="high", type=KnowledgeType.DECISION, title="H",
            content="c", lifecycle=LifecycleState.CREATED,
            confidence=1.0, provenance=Provenance(source_path="/y"),
        )
        assert obj2.confidence == 1.0

    def test_relations_accepts_list_with_any_objects(self):
        """relations is a plain list and accepts any objects (loose coupling)."""
        dummy_relation = {"target_id": "x", "type": "references"}
        obj = KnowledgeObject(
            id="ko-rel",
            type=KnowledgeType.SYNTHESIS,
            title="Rel Test",
            content="c",
            lifecycle=LifecycleState.ACTIVE,
            confidence=0.9,
            provenance=Provenance(source_path="/z"),
            relations=[dummy_relation],
        )
        assert len(obj.relations) == 1
        assert obj.relations[0] == dummy_relation

    def test_versions_accepts_list_of_versionref(self):
        """versions list works with VersionRef objects."""
        v1 = VersionRef(version_id="v1", timestamp=1000)
        v2 = VersionRef(version_id="v2", timestamp=2000, change_description="updated")
        obj = KnowledgeObject(
            id="ko-ver",
            type=KnowledgeType.PROCEDURE,
            title="Version Test",
            content="c",
            lifecycle=LifecycleState.CREATED,
            confidence=0.8,
            provenance=Provenance(source_path="/a"),
            versions=[v1, v2],
        )
        assert len(obj.versions) == 2
        assert obj.versions[0].version_id == "v1"
        assert obj.versions[1].version_id == "v2"

    def test_all_knowledge_types_work_in_object(self):
        """KnowledgeObject accepts every KnowledgeType value."""
        for kt in KnowledgeType:
            obj = KnowledgeObject(
                id=f"ko-{kt.value}",
                type=kt,
                title=f"Test {kt.value}",
                content="x",
                lifecycle=LifecycleState.CREATED,
                confidence=0.5,
                provenance=Provenance(source_path="/t"),
            )
            assert obj.type == kt, f"Failed for {kt}"

    def test_all_lifecycle_states_work_in_object(self):
        """KnowledgeObject accepts every LifecycleState value."""
        for ls in LifecycleState:
            obj = KnowledgeObject(
                id=f"ko-{ls.value}",
                type=KnowledgeType.CONCEPT,
                title=f"State {ls.value}",
                content="x",
                lifecycle=ls,
                confidence=0.5,
                provenance=Provenance(source_path="/t"),
            )
            assert obj.lifecycle == ls, f"Failed for {ls}"
