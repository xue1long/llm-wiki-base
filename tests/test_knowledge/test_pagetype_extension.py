"""Tests for the V4 four-value PageType contract."""
import tempfile
from pathlib import Path


from src.wiki.core.types import PageType, _TYPE_TO_DIR
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


class TestPageType:
    """V4 keeps the page type whitelist intentionally small."""

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
        """PageType has exactly the four V4 values."""
        members = list(PageType)
        assert len(members) == 4, f"Expected 4, got {len(members)}: {[m.value for m in members]}"


class TestTypeToDirMapping:
    """_TYPE_TO_DIR maps all V4 PageType values to WikiPaths properties."""

    def test_maps_all_four_values(self):
        assert len(_TYPE_TO_DIR) == 4

    def test_source_maps_to_wiki_sources(self):
        assert _TYPE_TO_DIR[PageType.SOURCE] == "wiki_sources"

    def test_entity_maps_to_wiki_entities(self):
        assert _TYPE_TO_DIR[PageType.ENTITY] == "wiki_entities"

    def test_concept_maps_to_wiki_concepts(self):
        assert _TYPE_TO_DIR[PageType.CONCEPT] == "wiki_concepts"

    def test_synthesis_maps_to_wiki_synthesis(self):
        assert _TYPE_TO_DIR[PageType.SYNTHESIS] == "wiki_synthesis"


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
