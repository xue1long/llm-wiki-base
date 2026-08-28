"""Test WikiPage <-> KnowledgeObject adapter (Task 1.3)."""
import pytest

from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
    VersionRef,
)
from src.knowledge.core.adapter import (
    wiki_page_to_knowledge_object,
    knowledge_object_to_wiki_page,
)
from src.wiki.core.types import WikiPage, PageType
from src.wiki.features.relations import Relation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ko_extra_full():
    """Return a representative _ko_extra dict for test reuse."""
    return {
        "lifecycle": "active",
        "confidence": 0.88,
        "provenance": {
            "source_path": "/docs/test.pdf",
            "page": 5,
            "quote": "verify this claim",
            "ingested_at": 1759430400,
            "ingestor_version": "2.0.0",
        },
        "versions": [
            {"version_id": "v1", "timestamp": 1000,
             "change_description": "created from candidate"},
        ],
        "sources": ["/raw/s1.md"],
        "processing_depth": "memory",
        "is_immutable": True,
        "last_used_at": 5000,
        "zombie_since": None,
        "tags": ["topic/science"],
        "category": "science",
        "taxonomy_sub": "physics",
    }


# ---------------------------------------------------------------------------
# 1. wiki_page_to_knowledge_object  — basic field mapping
# ---------------------------------------------------------------------------

class TestWikiPageToKnowledgeObjectBasic:
    """wiki_page_to_knowledge_object maps core fields correctly."""

    def test_maps_id_title_body_grade_heat_timestamps(self):
        wp = WikiPage(
            id="page-1", title="Hello World", type=PageType.CONCEPT,
            body="Body text.", grade="A", heat=75,
            created_at=100, updated_at=200,
        )
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.id == "page-1"
        assert ko.title == "Hello World"
        assert ko.content == "Body text."
        assert ko.grade == "A"
        assert ko.heat == 75
        assert ko.created_at == 100
        assert ko.updated_at == 200

    def test_maps_source_to_document(self):
        wp = WikiPage(id="src", title="S", type=PageType.SOURCE)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.type == KnowledgeType.DOCUMENT

    @pytest.mark.parametrize("pt,kt_str", [
        (PageType.SOURCE, "document"),
        (PageType.ENTITY, "entity"),
        (PageType.CONCEPT, "concept"),
        (PageType.CLAIM, "claim"),
        (PageType.DECISION, "decision"),
        (PageType.PROCEDURE, "procedure"),
        (PageType.EVENT, "event"),
        (PageType.SYNTHESIS, "synthesis"),
    ])
    def test_maps_each_page_type(self, pt, kt_str):
        wp = WikiPage(id="t", title="T", type=pt)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.type == KnowledgeType(kt_str)

    def test_relations_preserved(self):
        r = Relation(target_id="t-1", type="references", weight=0.75, context="see")
        wp = WikiPage(id="r", title="R", type=PageType.CONCEPT,
                      relations=[r])
        ko = wiki_page_to_knowledge_object(wp)
        assert len(ko.relations) == 1
        assert ko.relations[0] is r  # same object passed through


# ---------------------------------------------------------------------------
# 2. knowledge_object_to_wiki_page  — basic field mapping
# ---------------------------------------------------------------------------

class TestKnowledgeObjectToWikiPageBasic:
    """knowledge_object_to_wiki_page maps core fields correctly."""

    def test_maps_id_title_body_grade_heat_timestamps(self):
        ko = KnowledgeObject(
            id="ko-1", type=KnowledgeType.CONCEPT,
            title="Concept Title", content="Markdown body.",
            lifecycle=LifecycleState.ACTIVE, confidence=0.8,
            provenance=Provenance(source_path="/x.pdf"),
            grade="C", heat=30, created_at=300, updated_at=400,
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.id == "ko-1"
        assert wp.title == "Concept Title"
        assert wp.body == "Markdown body."
        assert wp.grade == "C"
        assert wp.heat == 30
        assert wp.created_at == 300
        assert wp.updated_at == 400

    def test_maps_document_to_source(self):
        ko = KnowledgeObject(
            id="d", type=KnowledgeType.DOCUMENT, title="D", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path="/d"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.type == PageType.SOURCE

    @pytest.mark.parametrize("kt,pt_str", [
        (KnowledgeType.DOCUMENT, "source"),
        (KnowledgeType.ENTITY, "entity"),
        (KnowledgeType.CONCEPT, "concept"),
        (KnowledgeType.CLAIM, "claim"),
        (KnowledgeType.DECISION, "decision"),
        (KnowledgeType.PROCEDURE, "procedure"),
        (KnowledgeType.EVENT, "event"),
        (KnowledgeType.SYNTHESIS, "synthesis"),
    ])
    def test_maps_each_knowledge_type(self, kt, pt_str):
        ko = KnowledgeObject(
            id="t", type=kt, title="T", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path="/x"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.type == PageType(pt_str)

    def test_default_wp_fields_when_no_ko_extra(self):
        """KO created from scratch (no _ko_extra) yields sensible WP defaults."""
        ko = KnowledgeObject(
            id="fresh", type=KnowledgeType.ENTITY, title="E", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path="/x"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.sources == ["/x"]  # seeded from provenance.source_path
        assert wp.processing_depth == "concept"
        assert wp.is_immutable is False
        assert wp.last_used_at == 0
        assert wp.zombie_since is None
        assert wp.tags == []
        assert wp.category == ""
        assert wp.taxonomy_sub == ""

    def test_all_provenance_source_paths_survive_adapter_round_trip(self):
        ko = KnowledgeObject(
            id="multi-source", type=KnowledgeType.CLAIM, title="C", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(
                source_path="/a.md", source_paths=("/a.md", "/b.md"),
            ),
        )

        round_tripped = knowledge_object_to_wiki_page(
            wiki_page_to_knowledge_object(knowledge_object_to_wiki_page(ko))
        )

        assert round_tripped.sources == ["/a.md", "/b.md"]

    def test_relations_preserved(self):
        r = Relation(target_id="t-2", type="supports", weight=0.9)
        ko = KnowledgeObject(
            id="ko-r", type=KnowledgeType.CONCEPT, title="R", content="c",
            lifecycle=LifecycleState.ACTIVE, confidence=0.7,
            provenance=Provenance(source_path="/y"),
            relations=[r],
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert len(wp.relations) == 1
        assert wp.relations[0].target_id == "t-2"
        assert wp.relations[0].type == "supports"


# ---------------------------------------------------------------------------
# 3. Round-trip: wp -> ko -> wp
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """wp -> ko -> wp preserves all original WikiPage fields."""

    def test_full_round_trip_preserves_all_fields(self):
        wp1 = WikiPage(
            id="round-trip-1",
            title="Round Trip Page",
            type=PageType.SYNTHESIS,
            sources=["/raw/a.md", "/raw/b.md"],
            body="# Section\n\nParagraph.",
            relations=[
                Relation(target_id="other", type="references", weight=0.5,
                         context="cites section 3"),
            ],
            grade="A",
            processing_depth="memory",
            is_immutable=True,
            heat=90,
            last_used_at=5000,
            zombie_since=None,
            tags=["topic/math", "status/reviewed"],
            category="mathematics",
            taxonomy_sub="algebra",
            created_at=1722556800000,
            updated_at=1722556899999,
        )

        ko = wiki_page_to_knowledge_object(wp1)
        wp2 = knowledge_object_to_wiki_page(ko)

        # dataclass __eq__ catches field differences
        assert wp1 == wp2, f"Round-trip mismatch: {wp1} != {wp2}"

        # Exhaustive assertion for clarity
        assert wp2.id == wp1.id
        assert wp2.title == wp1.title
        assert wp2.type == wp1.type
        assert wp2.sources == wp1.sources
        assert wp2.body == wp1.body
        assert len(wp2.relations) == 1
        assert wp2.relations[0].target_id == wp1.relations[0].target_id
        assert wp2.relations[0].type == wp1.relations[0].type
        assert wp2.relations[0].weight == wp1.relations[0].weight
        assert wp2.relations[0].context == wp1.relations[0].context
        assert wp2.grade == wp1.grade
        assert wp2.processing_depth == wp1.processing_depth
        assert wp2.is_immutable == wp1.is_immutable
        assert wp2.heat == wp1.heat
        assert wp2.last_used_at == wp1.last_used_at
        assert wp2.zombie_since == wp1.zombie_since
        assert wp2.tags == wp1.tags
        assert wp2.category == wp1.category
        assert wp2.taxonomy_sub == wp1.taxonomy_sub
        assert wp2.created_at == wp1.created_at
        assert wp2.updated_at == wp1.updated_at

    def test_minimal_wp_round_trip(self):
        """Round-trip with only required fields."""
        wp1 = WikiPage(id="min", title="Min", type=PageType.CONCEPT)
        ko = wiki_page_to_knowledge_object(wp1)
        wp2 = knowledge_object_to_wiki_page(ko)
        assert wp2.id == "min"
        assert wp2.title == "Min"
        assert wp2.type == PageType.CONCEPT
        assert wp2.body == ""
        assert wp2.heat == 50
        assert wp2.grade == "B"

    def test_ko_extra_survives_round_trip(self):
        """_ko_extra dict content is preserved through wp -> ko -> wp.

        WP-frontmatter fields (sources, processing_depth, etc.) that are
        set in _ko_extra must also be set on the WikiPage itself — the WP
        field is the authoritative source and overwrites _ko_extra during
        wp_to_ko.
        """
        extra_in = _make_ko_extra_full()
        wp1 = WikiPage(
            id="extra-rt", title="E", type=PageType.EVENT,
            sources=extra_in["sources"],
            processing_depth=extra_in["processing_depth"],
            is_immutable=extra_in["is_immutable"],
            last_used_at=extra_in["last_used_at"],
            tags=extra_in["tags"],
            category=extra_in["category"],
            taxonomy_sub=extra_in["taxonomy_sub"],
        )
        wp1._ko_extra = extra_in

        ko = wiki_page_to_knowledge_object(wp1)
        wp2 = knowledge_object_to_wiki_page(ko)

        assert hasattr(wp2, '_ko_extra')
        extra = wp2._ko_extra
        # KO-specific fields survive
        assert extra["lifecycle"] == "active"
        assert extra["confidence"] == 0.88
        assert extra["provenance"]["source_path"] == "/docs/test.pdf"
        assert extra["provenance"]["page"] == 5
        assert extra["versions"][0]["version_id"] == "v1"
        # WP-frontmatter fields survive (authoritative from WP fields +
        # provenance.source_path seeded by the adapter)
        assert extra["sources"] == ["/raw/s1.md", "/docs/test.pdf"]
        assert extra["processing_depth"] == "memory"
        assert extra["is_immutable"] is True


# ---------------------------------------------------------------------------
# 4. _ko_extra storage / retrieval
# ---------------------------------------------------------------------------

class TestKoExtraStorageRetrieval:
    """_ko_extra correctly stores and retrieves KO-specific fields."""

    def test_lifecycle_stored_and_retrieved(self):
        """All 8 lifecycle states round-trip through _ko_extra."""
        for ls in LifecycleState:
            wp = WikiPage(id=f"ls-{ls.value}", title="T", type=PageType.CONCEPT)
            wp._ko_extra = {"lifecycle": ls.value, "confidence": 0.5,
                            "provenance": {"source_path": "/x"},
                            "versions": []}
            ko = wiki_page_to_knowledge_object(wp)
            assert ko.lifecycle == ls, f"Failed for {ls}"

    def test_confidence_stored_as_float(self):
        wp = WikiPage(id="c", title="C", type=PageType.CONCEPT)
        wp._ko_extra = {"lifecycle": "active", "confidence": 0.123,
                        "provenance": {"source_path": "/x"}, "versions": []}
        ko = wiki_page_to_knowledge_object(wp)
        assert isinstance(ko.confidence, float)
        assert ko.confidence == 0.123

    def test_provenance_all_fields_stored(self):
        wp = WikiPage(id="p", title="P", type=PageType.CONCEPT)
        wp._ko_extra = {
            "lifecycle": "active",
            "confidence": 0.9,
            "provenance": {
                "source_path": "/data/doc.md",
                "page": 42,
                "quote": "exact words",
                "ingested_at": 1759430400,
                "ingestor_version": "3.1.4",
            },
            "versions": [],
        }
        ko = wiki_page_to_knowledge_object(wp)
        p = ko.provenance
        assert p.source_path == "/data/doc.md"
        assert p.page == 42
        assert p.quote == "exact words"
        assert p.ingested_at == 1759430400
        assert p.ingestor_version == "3.1.4"

    def test_provenance_none_page_survives(self):
        wp = WikiPage(id="p2", title="P2", type=PageType.CONCEPT)
        wp._ko_extra = {
            "lifecycle": "active", "confidence": 0.9,
            "provenance": {"source_path": "/a", "page": None,
                           "quote": "", "ingested_at": 0,
                           "ingestor_version": ""},
            "versions": [],
        }
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.provenance.page is None

    def test_versions_list_stored_and_retrieved(self):
        wp = WikiPage(id="v", title="V", type=PageType.CONCEPT)
        wp._ko_extra = {
            "lifecycle": "active",
            "confidence": 1.0,
            "provenance": {"source_path": "/x"},
            "versions": [
                {"version_id": "v1", "timestamp": 100,
                 "change_description": "first"},
                {"version_id": "v2", "timestamp": 200,
                 "change_description": "second"},
            ],
        }
        ko = wiki_page_to_knowledge_object(wp)
        assert len(ko.versions) == 2
        assert ko.versions[0].version_id == "v1"
        assert ko.versions[0].timestamp == 100
        assert ko.versions[0].change_description == "first"
        assert ko.versions[1].version_id == "v2"

    def test_ko_to_wp_stores_ko_extra_on_instance(self):
        """knowledge_object_to_wiki_page attaches _ko_extra to the result."""
        ko = KnowledgeObject(
            id="store", type=KnowledgeType.CLAIM, title="S", content="c",
            lifecycle=LifecycleState.REVIEWING, confidence=0.55,
            provenance=Provenance(
                source_path="/review/notes.pdf", page=3,
                quote="needs verification", ingested_at=9999,
                ingestor_version="0.1",
            ),
            versions=[
                VersionRef(version_id="v0", timestamp=50,
                           change_description="draft"),
            ],
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert hasattr(wp, '_ko_extra')

        extra = wp._ko_extra
        assert extra["lifecycle"] == "reviewing"
        assert extra["confidence"] == 0.55
        assert extra["provenance"]["source_path"] == "/review/notes.pdf"
        assert extra["provenance"]["page"] == 3
        assert extra["provenance"]["quote"] == "needs verification"
        assert extra["provenance"]["ingested_at"] == 9999
        assert extra["provenance"]["ingestor_version"] == "0.1"
        assert len(extra["versions"]) == 1
        assert extra["versions"][0]["version_id"] == "v0"
        assert extra["versions"][0]["change_description"] == "draft"


# ---------------------------------------------------------------------------
# 5. content <-> body mapping
# ---------------------------------------------------------------------------

class TestContentBodyMapping:
    """KnowledgeObject.content <-> WikiPage.body mapping."""

    def test_body_to_content(self):
        wp = WikiPage(id="b2c", title="B2C", type=PageType.CONCEPT,
                      body="## Section\n\nContent here.")
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.content == "## Section\n\nContent here."

    def test_content_to_body(self):
        ko = KnowledgeObject(
            id="c2b", type=KnowledgeType.CONCEPT, title="C2B",
            content="# Title\n\nParagraph with [[link]].",
            lifecycle=LifecycleState.ACTIVE, confidence=1.0,
            provenance=Provenance(source_path="/z"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.body == "# Title\n\nParagraph with [[link]]."

    def test_empty_content_round_trip(self):
        wp = WikiPage(id="empty", title="Empty", type=PageType.CLAIM)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.content == ""
        wp2 = knowledge_object_to_wiki_page(ko)
        assert wp2.body == ""

    def test_multiline_markdown_round_trip(self):
        md = "---\n# Header\n\n- item 1\n- item 2\n\n```python\nprint('hi')\n```\n"
        wp = WikiPage(id="md", title="MD", type=PageType.CONCEPT, body=md)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.content == md
        wp2 = knowledge_object_to_wiki_page(ko)
        assert wp2.body == md


# ---------------------------------------------------------------------------
# 6. Missing _ko_extra (old pages) — defaults applied
# ---------------------------------------------------------------------------

class TestMissingKoExtra:
    """WikiPage with missing _ko_extra uses safe defaults."""

    def test_no_attribute_no_frontmatter_key(self):
        """Old page with no _ko_extra at all — all KO-specific fields get defaults."""
        wp = WikiPage(id="old", title="Old Page", type=PageType.CONCEPT)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.lifecycle == LifecycleState.CREATED
        assert ko.confidence == 0.0
        assert ko.provenance.source_path == ""
        assert ko.provenance.page is None
        assert ko.provenance.quote == ""
        assert ko.provenance.ingested_at == 0
        assert ko.provenance.ingestor_version == ""
        assert ko.versions == []

    def test_empty_ko_extra_dict(self):
        wp = WikiPage(id="empty-extra", title="E", type=PageType.CONCEPT)
        wp._ko_extra = {}
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.lifecycle == LifecycleState.CREATED
        assert ko.confidence == 0.0

    def test_partial_ko_extra(self):
        """Only some _ko_extra keys present — missing ones get defaults."""
        wp = WikiPage(id="partial", title="P", type=PageType.CONCEPT)
        wp._ko_extra = {
            "lifecycle": "deprecated",
            "versions": [],
        }
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.lifecycle == LifecycleState.DEPRECATED
        assert ko.confidence == 0.0  # missing, default
        assert ko.provenance.source_path == ""  # missing, default


# ---------------------------------------------------------------------------
# 7. All 8 PageType values round-trip correctly
# ---------------------------------------------------------------------------

class TestAllPageTypeRoundTrip:
    """Every PageType <-> KnowledgeType combination round-trips."""

    @pytest.mark.parametrize("pt,expected_kt", [
        (PageType.SOURCE, KnowledgeType.DOCUMENT),
        (PageType.ENTITY, KnowledgeType.ENTITY),
        (PageType.CONCEPT, KnowledgeType.CONCEPT),
        (PageType.CLAIM, KnowledgeType.CLAIM),
        (PageType.DECISION, KnowledgeType.DECISION),
        (PageType.PROCEDURE, KnowledgeType.PROCEDURE),
        (PageType.EVENT, KnowledgeType.EVENT),
        (PageType.SYNTHESIS, KnowledgeType.SYNTHESIS),
    ])
    def test_wp_to_ko_type_mapping(self, pt, expected_kt):
        wp = WikiPage(id=f"rt-{pt.value}", title="T", type=pt)
        ko = wiki_page_to_knowledge_object(wp)
        assert ko.type == expected_kt, f"{pt} -> {ko.type}, expected {expected_kt}"

    @pytest.mark.parametrize("kt,expected_pt", [
        (KnowledgeType.DOCUMENT, PageType.SOURCE),
        (KnowledgeType.ENTITY, PageType.ENTITY),
        (KnowledgeType.CONCEPT, PageType.CONCEPT),
        (KnowledgeType.CLAIM, PageType.CLAIM),
        (KnowledgeType.DECISION, PageType.DECISION),
        (KnowledgeType.PROCEDURE, PageType.PROCEDURE),
        (KnowledgeType.EVENT, PageType.EVENT),
        (KnowledgeType.SYNTHESIS, PageType.SYNTHESIS),
    ])
    def test_ko_to_wp_type_mapping(self, kt, expected_pt):
        ko = KnowledgeObject(
            id=f"rt-{kt.value}", type=kt, title="T", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path="/x"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        assert wp.type == expected_pt, f"{kt} -> {wp.type}, expected {expected_pt}"

    @pytest.mark.parametrize("pt", list(PageType))
    def test_full_round_trip_each_type(self, pt):
        wp = WikiPage(id=f"full-{pt.value}", title="T", type=pt)
        ko = wiki_page_to_knowledge_object(wp)
        wp2 = knowledge_object_to_wiki_page(ko)
        assert wp2.type == pt, f"Round-trip failed for {pt}: got {wp2.type}"

    @pytest.mark.parametrize("kt", list(KnowledgeType))
    def test_ko_wp_ko_round_trip_each_type(self, kt):
        ko = KnowledgeObject(
            id=f"full-{kt.value}", type=kt, title="T", content="c",
            lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path="/x"),
        )
        wp = knowledge_object_to_wiki_page(ko)
        ko2 = wiki_page_to_knowledge_object(wp)
        assert ko2.type == kt, f"Round-trip failed for {kt}: got {ko2.type}"
