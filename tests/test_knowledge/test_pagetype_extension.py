"""Test PageType extension from 4 to 8 values (Task 1.0)."""
import tempfile
from pathlib import Path


from src.wiki.core.types import PageType, _TYPE_TO_DIR
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


class TestNewPageTypeValues:
    """Task 1.0: PageType extended from 4 to 8 values."""

    def test_new_enum_values_exist(self):
        """CLAIM, DECISION, PROCEDURE, EVENT are available on PageType."""
        assert hasattr(PageType, "CLAIM")
        assert hasattr(PageType, "DECISION")
        assert hasattr(PageType, "PROCEDURE")
        assert hasattr(PageType, "EVENT")

    def test_new_values_serialize(self):
        """New PageType values serialize to correct strings."""
        assert PageType.CLAIM.value == "claim"
        assert PageType.DECISION.value == "decision"
        assert PageType.PROCEDURE.value == "procedure"
        assert PageType.EVENT.value == "event"

    def test_new_values_deserialize(self):
        """New PageType values deserialize from strings."""
        assert PageType("claim") == PageType.CLAIM
        assert PageType("decision") == PageType.DECISION
        assert PageType("procedure") == PageType.PROCEDURE
        assert PageType("event") == PageType.EVENT

    def test_existing_values_unchanged(self):
        """Existing 4 PageType values still work."""
        assert PageType.SOURCE.value == "source"
        assert PageType.ENTITY.value == "entity"
        assert PageType.CONCEPT.value == "concept"
        assert PageType.SYNTHESIS.value == "synthesis"
        assert PageType("source") == PageType.SOURCE
        assert PageType("entity") == PageType.ENTITY
        assert PageType("concept") == PageType.CONCEPT
        assert PageType("synthesis") == PageType.SYNTHESIS

    def test_total_enum_count(self):
        """PageType now has exactly 8 values."""
        members = list(PageType)
        assert len(members) == 8, f"Expected 8, got {len(members)}: {[m.value for m in members]}"


class TestTypeToDirMapping:
    """_TYPE_TO_DIR maps all 8 PageType values to WikiPaths property names."""

    def test_maps_all_eight_values(self):
        assert len(_TYPE_TO_DIR) == 8

    def test_source_maps_to_wiki_sources(self):
        assert _TYPE_TO_DIR[PageType.SOURCE] == "wiki_sources"

    def test_entity_maps_to_wiki_entities(self):
        assert _TYPE_TO_DIR[PageType.ENTITY] == "wiki_entities"

    def test_concept_maps_to_wiki_concepts(self):
        assert _TYPE_TO_DIR[PageType.CONCEPT] == "wiki_concepts"

    def test_synthesis_maps_to_wiki_synthesis(self):
        assert _TYPE_TO_DIR[PageType.SYNTHESIS] == "wiki_synthesis"

    def test_claim_maps_to_wiki_claims(self):
        assert _TYPE_TO_DIR[PageType.CLAIM] == "wiki_claims"

    def test_decision_maps_to_wiki_decisions(self):
        assert _TYPE_TO_DIR[PageType.DECISION] == "wiki_decisions"

    def test_procedure_maps_to_wiki_concepts(self):
        assert _TYPE_TO_DIR[PageType.PROCEDURE] == "wiki_concepts"

    def test_event_maps_to_wiki_concepts(self):
        assert _TYPE_TO_DIR[PageType.EVENT] == "wiki_concepts"


class TestWikiPathsNewProperties:
    """WikiPaths gains wiki_claims and wiki_decisions properties."""

    def test_wiki_claims_property(self):
        paths = WikiPaths(Path("/fake/root"))
        assert paths.wiki_claims == Path("/fake/root/wiki/claims")

    def test_wiki_decisions_property(self):
        paths = WikiPaths(Path("/fake/root"))
        assert paths.wiki_decisions == Path("/fake/root/wiki/decisions")

    def test_existing_properties_unchanged(self):
        """Existing WikiPaths properties still work."""
        paths = WikiPaths(Path("/fake"))
        assert paths.wiki_sources == Path("/fake/wiki/sources")
        assert paths.wiki_entities == Path("/fake/wiki/entities")
        assert paths.wiki_concepts == Path("/fake/wiki/concepts")
        assert paths.wiki_synthesis == Path("/fake/wiki/synthesis")


class TestEnsureKnowledgeBase:
    """ensure_knowledge_base() creates the new directories."""

    def test_creates_claims_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_knowledge_base(tmp)
            assert paths.wiki_claims.exists()
            assert paths.wiki_claims.is_dir()

    def test_creates_decisions_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_knowledge_base(tmp)
            assert paths.wiki_decisions.exists()
            assert paths.wiki_decisions.is_dir()

    def test_existing_directories_still_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_knowledge_base(tmp)
            assert paths.wiki_sources.exists()
            assert paths.wiki_entities.exists()
            assert paths.wiki_concepts.exists()
            assert paths.wiki_synthesis.exists()
            assert paths.wiki_stubs.exists()
