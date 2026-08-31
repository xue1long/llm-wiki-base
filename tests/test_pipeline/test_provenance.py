"""Tests for Task 2.3 鈥?page-level provenance for PDFs."""
import pytest


# ---------------------------------------------------------------------------
# 2.3a 鈥?PDF page marker injection
# ---------------------------------------------------------------------------

class TestPdfPageMarkers:
    def test_extract_pdf_injects_page_markers(self, monkeypatch):
        """PDF extraction injects <!-- page: N --> before each page's text."""
        from src.utils.extract import pdf as pdf_mod
        import pypdf

        class FakePage:
            def extract_text(self):
                return "Page content."

        class FakeReader:
            is_encrypted = False
            pages = [FakePage(), FakePage(), FakePage()]

        monkeypatch.setattr(pypdf, "PdfReader", lambda path: FakeReader)
        text = pdf_mod.extract_pdf_text("fake.pdf")
        assert "<!-- page: 1 -->" in text
        assert "<!-- page: 2 -->" in text
        assert "<!-- page: 3 -->" in text

    def test_empty_page_skips_marker(self, monkeypatch):
        """Pages with no text don't produce markers."""
        from src.utils.extract import pdf as pdf_mod
        import pypdf

        class FakePage1:
            def extract_text(self):
                return "First."
        class FakePage2:
            def extract_text(self):
                return ""  # empty
        class FakePage3:
            def extract_text(self):
                return "Third."

        class FakeReader:
            is_encrypted = False
            pages = [FakePage1(), FakePage2(), FakePage3()]

        monkeypatch.setattr(pypdf, "PdfReader", lambda path: FakeReader)
        text = pdf_mod.extract_pdf_text("fake.pdf")
        assert "<!-- page: 1 -->" in text
        assert "<!-- page: 2 -->" not in text
        assert "<!-- page: 3 -->" in text


# ---------------------------------------------------------------------------
# 2.3a (safety) 鈥?markers survive sanitizer
# ---------------------------------------------------------------------------

class TestPageMarkersSurviveSanitizer:
    def test_clean_source_text_preserves_page_markers(self):
        """clean_source_text does NOT strip <!-- page: N --> markers."""
        from src.pipeline._pipeline_common import clean_source_text
        text = "<!-- page: 1 -->\nSome content.\n<!-- page: 2 -->\nMore content."
        cleaned = clean_source_text(text)
        assert "<!-- page: 1 -->" in cleaned
        assert "<!-- page: 2 -->" in cleaned

    def test_denoise_source_text_preserves_page_markers(self):
        """denoise_source_text (denoiser) preserves page markers."""
        from src.pipeline._pipeline_common import denoise_source_text
        text = "<!-- page: 1 -->\nSome content.\n<!-- page: 2 -->\nMore."
        cleaned = denoise_source_text(text)
        assert "<!-- page: 1 -->" in cleaned
        assert "<!-- page: 2 -->" in cleaned


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 2.3c 鈥?generate_from_candidate sets _ko_extra.provenance
# ---------------------------------------------------------------------------

class TestGenerateFromCandidateProvenance:
    @pytest.mark.asyncio
    async def test_generate_sets_ko_extra_provenance(self, tmp_path):
        """generate_from_candidate sets _ko_extra.provenance on every WikiPage."""
        from src.pipeline.generator import generate_from_candidate
        from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
        from src.knowledge.core.object import KnowledgeType
        from src.wiki.core.paths import WikiPaths

        candidate = KnowledgeCandidate(
            id="c1", source_id="test.pdf", type=KnowledgeType.CONCEPT,
            title="Test Concept", claims=[
                {"statement": "A fact", "confidence": 0.9, "evidence_refs": [0]},
            ], confidence=0.85,
            evidence=[
                {"source_path": "test.pdf", "page": 5, "quote": "supporting text"},
            ],
            raw_llm_output={}, status=CandidateStatus.VALIDATED,
        )

        paths = WikiPaths(tmp_path)
        paths.root.mkdir(parents=True, exist_ok=True)

        from unittest.mock import AsyncMock
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = type("R", (), {
            "content": '{"pages": [{"id": "test-concept", "type": "concept", '
                      '"title": "Test Concept", '
                      '"slots": {"overview": "A concept.", '
                      '"related_concepts": "- [[other]]", '
                      '"references": "- [[test-pdf_a1b2c3d4]]"}}]}'
        })()

        pages = await generate_from_candidate(
            candidate=candidate,
            paths=paths,
            existing_wiki_index="",
            provider=mock_provider,
            source_slug_map={"test.pdf": "test-pdf_a1b2c3d4"},
        )
        assert len(pages) >= 1
        for page in pages:
            assert hasattr(page, "_ko_extra")
            assert isinstance(page._ko_extra, dict)
            assert "provenance" in page._ko_extra
            assert page._ko_extra["provenance"]["page"] == 5
            assert page._ko_extra["provenance"]["quote"] == "supporting text"
            assert page._ko_extra["provenance"]["source_path"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_generate_no_evidence_provenance_none(self, tmp_path):
        """When candidate has no evidence, provenance page is None."""
        from src.pipeline.generator import generate_from_candidate
        from src.knowledge.core.candidate import CandidateStatus, KnowledgeCandidate
        from src.knowledge.core.object import KnowledgeType
        from src.wiki.core.paths import WikiPaths

        candidate = KnowledgeCandidate(
            id="c2", source_id="test.md", type=KnowledgeType.CONCEPT,
            title="Test", claims=[
                {"statement": "A fact", "confidence": 0.9, "evidence_refs": []},
            ], confidence=0.7,
            evidence=[],
            raw_llm_output={}, status=CandidateStatus.VALIDATED,
        )

        paths = WikiPaths(tmp_path)
        paths.root.mkdir(parents=True, exist_ok=True)

        from unittest.mock import AsyncMock
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = type("R", (), {
            "content": '{"pages": [{"id": "test", "type": "concept", '
                      '"title": "Test", '
                      '"slots": {"overview": "Overview.", '
                      '"related_concepts": "- [[other]]", '
                      '"references": "- [[test_a1b2c3d4]]"}}]}'
        })()

        pages = await generate_from_candidate(
            candidate=candidate,
            paths=paths,
            existing_wiki_index="",
            provider=mock_provider,
            source_slug_map={"test.md": "test_a1b2c3d4"},
        )
        assert len(pages) >= 1
        for page in pages:
            prov = page._ko_extra["provenance"]
            assert prov["page"] is None
            assert prov["quote"] == ""


# ---------------------------------------------------------------------------
# 2.3c 鈥?WikiPage.to_frontmatter_dict includes _ko_extra
# ---------------------------------------------------------------------------

class TestFrontmatterV4OmitsKoExtra:
    """V4 (ADR-002, 2026-08-31): _ko_extra is NOT in the 8-key whitelist.

    Legacy pages still carry _ko_extra.provenance in their frontmatter and
    from_dict() restores it to the in-memory WikiPage, but new writes
    drop _ko_extra entirely. The provenance payload remains on the
    in-memory WikiPage for code that needs it.
    """
    def test_to_frontmatter_dict_omits_ko_extra_v4(self):
        """V4: to_frontmatter_dict never emits _ko_extra."""
        from src.wiki.core.types import PageType, WikiPage
        page = WikiPage(
            id="test-id", title="Test Page", type=PageType.CONCEPT,
        )
        page._ko_extra = {"provenance": {"source_path": "test.pdf", "page": 3, "quote": "text"}}
        d = page.to_frontmatter_dict()
        assert "_ko_extra" not in d
        # In-memory attribute preserved.
        assert page._ko_extra["provenance"]["page"] == 3

    def test_to_frontmatter_dict_no_ko_extra_omitted(self):
        """to_frontmatter_dict omits _ko_extra when not set."""
        from src.wiki.core.types import PageType, WikiPage
        page = WikiPage(
            id="test-id", title="Test Page", type=PageType.CONCEPT,
        )
        d = page.to_frontmatter_dict()
        assert "_ko_extra" not in d


# ---------------------------------------------------------------------------
# 2.3d 鈥?Analyzer prompt contains page guidance
# ---------------------------------------------------------------------------

class TestAnalyzerPromptPageGuidance:
    def test_analyzer_json_prompt_has_page_guidance(self):
        """ANALYZER_JSON_PROMPT includes page number instructions."""
        from src.pipeline.analyzer import ANALYZER_JSON_PROMPT
        assert "page: N" in ANALYZER_JSON_PROMPT
        assert "page number" in ANALYZER_JSON_PROMPT.lower()
