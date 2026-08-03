"""Tests for src/pipeline/stages/claim_extractor.py — ClaimExtractorStage."""
from pathlib import Path


from src.knowledge.claims.model import Claim, ClaimStatus, ClaimType, Evidence
from src.knowledge.claims.parser import ClaimParser
from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.pipeline.stages.claim_extractor import (
    CLAIMS_EXTRACTED_EVENT,
    ClaimExtractorStage,
)
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validated_candidate(**overrides) -> KnowledgeCandidate:
    """Build a VALIDATED KnowledgeCandidate with 2 claims + 2 evidence items."""
    defaults = dict(
        id="cand-test001",
        source_id="raw/sources/doc1.md",
        type=KnowledgeType.CONCEPT,
        title="Test Concept",
        claims=[
            {
                "statement": "Backprop is a key algorithm for training neural networks",
                "confidence": 0.95,
                "evidence_refs": [0],
            },
            {
                "statement": "Gradient descent minimizes the loss function",
                "confidence": 0.90,
                "evidence_refs": [0, 1],
            },
        ],
        confidence=0.85,
        evidence=[
            {
                "source_path": "raw/sources/doc1.md",
                "page": 3,
                "quote": "Backprop computes gradients efficiently.",
            },
            {
                "source_path": "raw/sources/doc1.md",
                "page": 5,
                "quote": "Gradient descent updates weights iteratively.",
            },
        ],
        raw_llm_output={"source_id": "raw/sources/doc1.md", "type": "concept"},
        status=CandidateStatus.VALIDATED,
    )
    defaults.update(overrides)
    return KnowledgeCandidate(**defaults)


def _make_tmp_wiki_paths(tmp_path: Path) -> WikiPaths:
    """Create a minimal wiki directory tree and return WikiPaths."""
    paths = WikiPaths(tmp_path)
    paths.wiki_claims.mkdir(parents=True, exist_ok=True)
    return paths


# ---------------------------------------------------------------------------
# Extract tests
# ---------------------------------------------------------------------------

class TestClaimExtractorExtract:
    """ClaimExtractorStage.extract(candidate) -> list[Claim]."""

    def test_extract_returns_claims_from_valid_candidate(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        assert len(claims) == 2
        for c in claims:
            assert isinstance(c, Claim)

    def test_extract_correct_statements(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        assert claims[0].statement == "Backprop is a key algorithm for training neural networks"
        assert claims[1].statement == "Gradient descent minimizes the loss function"

    def test_extract_confidence_values(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        assert claims[0].confidence == 0.95
        assert claims[1].confidence == 0.90

    def test_extract_default_type_is_fact(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        for c in claims:
            assert c.type == ClaimType.FACT

    def test_extract_default_status_is_pending(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        for c in claims:
            assert c.status == ClaimStatus.PENDING

    def test_extract_evidence_resolved(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        # Claim 0 has evidence_refs [0] → 1 evidence
        assert len(claims[0].evidence) == 1
        assert claims[0].evidence[0].source_path == "raw/sources/doc1.md"
        assert claims[0].evidence[0].page == 3
        assert claims[0].evidence[0].quote == "Backprop computes gradients efficiently."

        # Claim 1 has evidence_refs [0, 1] → 2 evidence
        assert len(claims[1].evidence) == 2
        assert claims[1].evidence[1].page == 5

    def test_extract_source_objects_populated(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        for c in claims:
            assert c.source_objects == ["raw/sources/doc1.md"]

    def test_extract_claim_ids_sequential(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate()
        claims = stage.extract(candidate)

        assert claims[0].id == "cand-test001_c0"
        assert claims[1].id == "cand-test001_c1"

    def test_extract_empty_claims_returns_empty_list(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate(claims=[])
        claims = stage.extract(candidate)

        assert claims == []
        assert isinstance(claims, list)

    def test_extract_skips_claims_missing_statement(self):
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate(
            claims=[
                {"statement": "Valid claim", "confidence": 0.8, "evidence_refs": [0]},
                {"confidence": 0.5, "evidence_refs": [0]},  # no statement key
                {"statement": "Another valid claim", "confidence": 0.7, "evidence_refs": [0]},
            ],
        )
        claims = stage.extract(candidate)
        assert len(claims) == 2
        assert claims[0].statement == "Valid claim"
        assert claims[1].statement == "Another valid claim"


# ---------------------------------------------------------------------------
# Claim to KnowledgeObject conversion tests
# ---------------------------------------------------------------------------

class TestClaimToKnowledgeObject:
    """ClaimExtractorStage.claim_to_knowledge_object(claim) -> KnowledgeObject."""

    def test_returns_knowledge_object(self):
        stage = ClaimExtractorStage()
        claim = Claim(
            id="claim-001",
            statement="A test claim statement",
            type=ClaimType.FACT,
            confidence=0.9,
            evidence=[
                Evidence(source_path="src/doc1.md", page=1, quote="test quote"),
            ],
            status=ClaimStatus.PENDING,
            source_objects=["src/doc1.md"],
        )
        ko = stage.claim_to_knowledge_object(claim)

        assert isinstance(ko, KnowledgeObject)

    def test_type_is_claim(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.type == KnowledgeType.CLAIM

    def test_title_truncated_to_80_chars(self):
        stage = ClaimExtractorStage()
        long_statement = "A" * 120
        claim = Claim(id="c1", statement=long_statement, confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.title == long_statement[:80]
        assert len(ko.title) == 80

    def test_title_is_full_statement_when_short(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Short statement", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.title == "Short statement"

    def test_lifecycle_is_created(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.lifecycle == LifecycleState.CREATED

    def test_confidence_carried_over(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.73)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.confidence == 0.73

    def test_provenance_set_from_first_source_object(self):
        stage = ClaimExtractorStage()
        claim = Claim(
            id="c1",
            statement="Test",
            confidence=0.5,
            source_objects=["raw/sources/doc1.md", "raw/sources/doc2.md"],
        )
        ko = stage.claim_to_knowledge_object(claim)

        assert isinstance(ko.provenance, Provenance)
        assert ko.provenance.source_path == "raw/sources/doc1.md"
        assert ko.provenance.ingestor_version == "2.0.0"

    def test_provenance_empty_when_no_source_objects(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5, source_objects=[])
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.provenance.source_path == ""

    def test_content_contains_statement(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="The sky is blue", confidence=0.9)
        ko = stage.claim_to_knowledge_object(claim)

        assert "The sky is blue" in ko.content
        assert "## 声明" in ko.content

    def test_content_contains_metadata_section(self):
        stage = ClaimExtractorStage()
        claim = Claim(
            id="c1",
            statement="Test",
            type=ClaimType.OPINION,
            confidence=0.7,
            status=ClaimStatus.VERIFIED,
            source_objects=["src/doc.md"],
        )
        ko = stage.claim_to_knowledge_object(claim)

        assert "## 元数据" in ko.content
        assert "opinion" in ko.content
        assert "0.7" in ko.content
        assert "verified" in ko.content
        assert "src/doc.md" in ko.content

    def test_content_contains_evidence_section(self):
        stage = ClaimExtractorStage()
        claim = Claim(
            id="c1",
            statement="Test",
            confidence=0.5,
            evidence=[
                Evidence(source_path="src/doc.md", page=2, quote="exact quote text"),
            ],
            source_objects=["src/doc.md"],
        )
        ko = stage.claim_to_knowledge_object(claim)

        assert "## 证据" in ko.content
        assert "src/doc.md" in ko.content
        assert "exact quote text" in ko.content

    def test_content_no_evidence_section_when_empty(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5, evidence=[])
        ko = stage.claim_to_knowledge_object(claim)

        assert "(无证据)" in ko.content

    def test_versions_has_v1_entry(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert len(ko.versions) == 1
        assert ko.versions[0].version_id == "v1"
        assert "extracted from candidate claim" in ko.versions[0].change_description

    def test_heat_default_50(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.heat == 50

    def test_grade_default_b(self):
        stage = ClaimExtractorStage()
        claim = Claim(id="c1", statement="Test", confidence=0.5)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.grade == "B"

    def test_timestamps_carried_from_claim(self):
        import time
        stage = ClaimExtractorStage()
        now = int(time.time() * 1000)
        claim = Claim(id="c1", statement="Test", confidence=0.5, created_at=now - 1000, updated_at=now)
        ko = stage.claim_to_knowledge_object(claim)

        assert ko.created_at == now - 1000
        assert ko.updated_at == now


# ---------------------------------------------------------------------------
# Store claims tests
# ---------------------------------------------------------------------------

class TestStoreClaims:
    """ClaimExtractorStage.store_claims(claims, paths) -> list[WikiPage]."""

    def test_writes_claims_to_wiki_claims_directory(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(
                id="claim-store-1",
                statement="First claim statement",
                confidence=0.9,
                source_objects=["src/doc.md"],
            ),
            Claim(
                id="claim-store-2",
                statement="Second claim statement",
                confidence=0.8,
                source_objects=["src/doc.md"],
            ),
        ]

        pages = stage.store_claims(claims, paths)

        assert len(pages) == 2
        for p in pages:
            assert isinstance(p, WikiPage)

    def test_written_files_exist(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(id="claim-f1", statement="Test claim one", confidence=0.9, source_objects=["src/doc.md"]),
        ]
        stage.store_claims(claims, paths)

        claim_file = paths.wiki_claims / "claim-f1.md"
        assert claim_file.exists()

    def test_written_file_has_correct_frontmatter(self, tmp_path):
        import yaml
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(id="claim-fm1", statement="Test frontmatter", confidence=0.85, source_objects=["src/doc.md"]),
        ]
        stage.store_claims(claims, paths)

        claim_file = paths.wiki_claims / "claim-fm1.md"
        content = claim_file.read_text(encoding="utf-8")
        assert content.startswith("---")
        # Parse the frontmatter
        end = content.find("\n---", 4)
        fm_text = content[4:end]
        fm = yaml.safe_load(fm_text)

        assert fm["id"] == "claim-fm1"
        assert fm["type"] == "claim"
        assert fm["title"] == "Test frontmatter"

    def test_written_file_has_body_content(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(id="claim-body1", statement="Body test claim", confidence=0.9, source_objects=["src/doc.md"]),
        ]
        stage.store_claims(claims, paths)

        claim_file = paths.wiki_claims / "claim-body1.md"
        content = claim_file.read_text(encoding="utf-8")

        assert "## 声明" in content
        assert "Body test claim" in content
        assert "## 元数据" in content
        assert "## 证据" in content

    def test_multiple_claims_all_written(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(id=f"multi-{i}", statement=f"Statement {i}", confidence=0.8, source_objects=["src/doc.md"])
            for i in range(5)
        ]
        pages = stage.store_claims(claims, paths)

        assert len(pages) == 5
        for i in range(5):
            f = paths.wiki_claims / f"multi-{i}.md"
            assert f.exists()

    def test_empty_claims_no_files_written(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        pages = stage.store_claims([], paths)

        assert pages == []

    def test_returns_wiki_pages_with_correct_type(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claims = [
            Claim(id="type-test", statement="Type test", confidence=0.8, source_objects=["src/doc.md"]),
        ]
        pages = stage.store_claims(claims, paths)

        assert pages[0].type == PageType.CLAIM

    def test_round_trip_claim_to_page(self, tmp_path):
        """Verify Claim → KnowledgeObject → WikiPage → file round-trip."""
        from src.wiki.storage.page_writer import read_page
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        claim = Claim(
            id="roundtrip-1",
            statement="Round-trip test statement",
            type=ClaimType.HYPOTHESIS,
            confidence=0.88,
            evidence=[
                Evidence(source_path="src/doc.md", page=4, quote="supporting evidence"),
            ],
            status=ClaimStatus.PENDING,
            source_objects=["src/doc.md"],
        )
        stage.store_claims([claim], paths)

        # Read back
        claim_file = paths.wiki_claims / "roundtrip-1.md"
        page = read_page(claim_file)

        assert page.id == "roundtrip-1"
        assert page.type == PageType.CLAIM
        assert page.title == "Round-trip test statement"
        assert "Round-trip test statement" in page.body
        assert "## 声明" in page.body
        assert "supporting evidence" in page.body

    def test_rejected_candidate_status_still_extracts_claims(self, tmp_path):
        """Claims should still be extractable even if candidate is REJECTED
        (extraction is orthogonal to candidate lifecycle)."""
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()
        candidate = _make_validated_candidate(status=CandidateStatus.REJECTED)
        claims = stage.extract(candidate)

        assert len(claims) == 2
        pages = stage.store_claims(claims, paths)
        assert len(pages) == 2


# ---------------------------------------------------------------------------
# EventBus integration tests
# ---------------------------------------------------------------------------

class TestClaimExtractorEventBus:
    """ClaimExtractorStage EventBus integration."""

    def test_handle_candidate_validated_extracts_and_stores(self, tmp_path):
        from src.events.event_bus import event_bus as eb

        paths = _make_tmp_wiki_paths(tmp_path)
        candidate = _make_validated_candidate()
        stage = ClaimExtractorStage()

        # Collect events emitted by stage
        received_events = []

        def _on_claims_extracted(payload):
            received_events.append(payload)

        eb.on(CLAIMS_EXTRACTED_EVENT, _on_claims_extracted)

        try:
            stage.handle_candidate_validated({"candidate": candidate, "paths": paths})

            # Verify claims were written
            f1 = paths.wiki_claims / "cand-test001_c0.md"
            f2 = paths.wiki_claims / "cand-test001_c1.md"
            assert f1.exists()
            assert f2.exists()

            # Verify event was emitted
            assert len(received_events) == 1
            assert len(received_events[0]["claims"]) == 2
            assert len(received_events[0]["pages"]) == 2
            assert received_events[0]["candidate_id"] == "cand-test001"
        finally:
            eb.off(CLAIMS_EXTRACTED_EVENT, _on_claims_extracted)

    def test_handle_candidate_validated_empty_claims_emits_event(self, tmp_path):
        from src.events.event_bus import event_bus as eb

        paths = _make_tmp_wiki_paths(tmp_path)
        candidate = _make_validated_candidate(claims=[])
        stage = ClaimExtractorStage()

        received_events = []

        def _on_claims_extracted(payload):
            received_events.append(payload)

        eb.on(CLAIMS_EXTRACTED_EVENT, _on_claims_extracted)

        try:
            stage.handle_candidate_validated({"candidate": candidate, "paths": paths})

            assert len(received_events) == 1
            assert received_events[0]["claims"] == []
            assert received_events[0]["pages"] == []
        finally:
            eb.off(CLAIMS_EXTRACTED_EVENT, _on_claims_extracted)

    def test_handle_candidate_validated_bad_payload_no_crash(self, tmp_path):
        """Malformed payload should not crash."""
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        # Missing candidate
        stage.handle_candidate_validated({"paths": paths})

        # Wrong type for candidate
        stage.handle_candidate_validated({"candidate": "not_a_candidate", "paths": paths})

        # Empty dict
        stage.handle_candidate_validated({})

        # No crash = pass

    def test_register_and_unregister(self):
        stage = ClaimExtractorStage()

        assert not stage._registered
        stage.register()
        assert stage._registered

        # Idempotent
        stage.register()
        assert stage._registered

        stage.unregister()
        assert not stage._registered

    def test_custom_parser_injected(self):
        """ClaimExtractorStage should accept a custom ClaimParser."""
        custom = ClaimParser()
        stage = ClaimExtractorStage(claim_parser=custom)
        assert stage.parser is custom

    def test_default_parser_created(self):
        stage = ClaimExtractorStage()
        assert isinstance(stage.parser, ClaimParser)


# ---------------------------------------------------------------------------
# Integration: full flow with parser + store
# ---------------------------------------------------------------------------

class TestFullIntegration:
    """End-to-end: candidate → extract → store → verify on disk."""

    def test_full_flow_with_validated_candidate(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        candidate = _make_validated_candidate()
        stage = ClaimExtractorStage()

        # Step 1: extract
        claims = stage.extract(candidate)
        assert len(claims) == 2

        # Step 2: store
        pages = stage.store_claims(claims, paths)
        assert len(pages) == 2

        # Step 3: verify on disk
        for page in pages:
            f = paths.wiki_claims / f"{page.id}.md"
            assert f.exists()
            content = f.read_text(encoding="utf-8")
            assert "## 声明" in content
            assert page.title in content

    def test_claim_evidence_preserved_through_full_flow(self, tmp_path):
        from src.wiki.storage.page_writer import read_page
        paths = _make_tmp_wiki_paths(tmp_path)
        candidate = _make_validated_candidate()
        stage = ClaimExtractorStage()

        claims = stage.extract(candidate)
        pages = stage.store_claims(claims, paths)

        # The first claim should have evidence from page 3
        claim_file = paths.wiki_claims / f"{claims[0].id}.md"
        page = read_page(claim_file)
        assert "Backprop computes gradients efficiently" in page.body

    def test_multiple_candidates_independent_extraction(self, tmp_path):
        paths = _make_tmp_wiki_paths(tmp_path)
        stage = ClaimExtractorStage()

        cand1 = _make_validated_candidate(id="cand-a", claims=[
            {"statement": "Claim A1", "confidence": 0.9, "evidence_refs": [0]},
        ], evidence=[
            {"source_path": "src/a.md", "page": 1, "quote": "Evidence A"},
        ])
        cand2 = _make_validated_candidate(id="cand-b", claims=[
            {"statement": "Claim B1", "confidence": 0.8, "evidence_refs": [0]},
        ], evidence=[
            {"source_path": "src/b.md", "page": 2, "quote": "Evidence B"},
        ])

        claims1 = stage.extract(cand1)
        claims2 = stage.extract(cand2)

        stage.store_claims(claims1, paths)
        stage.store_claims(claims2, paths)

        assert (paths.wiki_claims / "cand-a_c0.md").exists()
        assert (paths.wiki_claims / "cand-b_c0.md").exists()
        assert (paths.wiki_claims / "cand-a_c0.md").read_text(encoding="utf-8") != \
               (paths.wiki_claims / "cand-b_c0.md").read_text(encoding="utf-8")
