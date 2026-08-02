"""Tests for ResearcherAgent — cross-source deep research with domain filtering."""

import asyncio
import time

import pytest

from src.agent.researcher import ResearchReport, ResearcherAgent
from src.knowledge.core.object import KnowledgeObject, KnowledgeType, LifecycleState
from src.knowledge.provenance.tracker import ProvenanceTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously (follows existing test_agent pattern)."""
    return asyncio.run(coro)


class MockSearchProvider:
    """Minimal mock matching the TavilyProvider.search interface."""

    def __init__(self, results=None):
        self.results = results if results is not None else []

    async def search(self, query, top_k=10):
        return list(self.results)


def _make_source(title, url, snippet):
    """Create a dict matching TavilyProvider search result shape."""
    return {"title": title, "url": url, "snippet": snippet}


# ---------------------------------------------------------------------------
# ResearchReport dataclass tests
# ---------------------------------------------------------------------------

class TestResearchReport:
    """ResearchReport dataclass field validation."""

    def test_all_fields_populated(self):
        """All seven fields are present and correctly stored."""
        now = int(time.time() * 1000)
        report = ResearchReport(
            id="r-123",
            question="What is Kafka?",
            summary="Kafka is a distributed streaming platform.",
            sources=[_make_source("Kafka Overview", "https://example.com/kafka", "Apache Kafka...")],
            confidence=0.7,
            claims=[{"text": "Kafka is a streaming platform.", "source_index": 0}],
            created_at=now,
        )
        assert report.id == "r-123"
        assert report.question == "What is Kafka?"
        assert "Kafka" in report.summary
        assert len(report.sources) == 1
        assert report.confidence == 0.7
        assert len(report.claims) == 1
        assert report.created_at == now

    def test_empty_sources_defaults(self):
        """A report with no sources should still have valid defaults."""
        now = int(time.time() * 1000)
        report = ResearchReport(
            id="r-empty",
            question="Unknown topic",
            summary="",
            sources=[],
            confidence=0.3,
            claims=[],
            created_at=now,
        )
        assert report.sources == []
        assert report.claims == []
        assert report.summary == ""
        assert report.confidence == 0.3

    def test_created_at_is_recent(self):
        """created_at should be a recent Unix ms timestamp."""
        now = int(time.time() * 1000)
        report = ResearchReport(
            id="r-time", question="X", summary="Y",
            sources=[], confidence=0.5, claims=[], created_at=now,
        )
        assert abs(report.created_at - now) <= 1000


# ---------------------------------------------------------------------------
# ResearcherAgent tests
# ---------------------------------------------------------------------------

class TestResearcherAgentResearch:
    """Tests for ResearcherAgent.research() — the main entry point."""

    def test_research_returns_research_report(self):
        """research() returns a ResearchReport instance."""
        mock = MockSearchProvider([_make_source("T1", "https://a.com/1", "S1")])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("What is Kafka?"))
        assert isinstance(report, ResearchReport)

    def test_report_has_generated_id(self):
        """Each research call generates a unique ID."""
        mock = MockSearchProvider([_make_source("T1", "https://a.com/1", "S1")])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("Test Q"))
        assert report.id.startswith("research-")
        assert len(report.id) > len("research-")

    def test_report_has_question(self):
        """The question field matches the input."""
        mock = MockSearchProvider([_make_source("T1", "https://a.com/1", "S1")])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("What is Kafka?"))
        assert report.question == "What is Kafka?"

    def test_report_has_sources(self):
        """Sources list is populated from web search results."""
        mock = MockSearchProvider([
            _make_source("A", "https://a.com/1", "Snippet A"),
            _make_source("B", "https://b.com/2", "Snippet B"),
        ])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("Test Q"))
        assert len(report.sources) == 2

    def test_sources_tagged_as_web_search(self):
        """Each source has source_type='web_search' with metadata."""
        mock = MockSearchProvider([_make_source("T1", "https://example.com/1", "Snippet")])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("Test Q"))
        for source in report.sources:
            assert source.get("source_type") == "web_search"
            assert "search_url" in source
            assert "retrieved_at" in source
            assert isinstance(source["retrieved_at"], int)

    def test_graceful_degradation_no_search_provider(self):
        """No web search provider — returns report with empty sources (no crash)."""
        agent = ResearcherAgent(web_search_provider=None)
        report = _run(agent.research("Test Q"))
        assert isinstance(report, ResearchReport)
        assert report.sources == []
        assert report.claims == []
        assert report.summary == ""

    def test_search_provider_error_returns_empty(self):
        """If the search provider raises, gracefully return empty sources."""
        class FailingProvider:
            async def search(self, query, top_k=10):
                raise RuntimeError("Search failed")

        agent = ResearcherAgent(web_search_provider=FailingProvider())
        report = _run(agent.research("Test Q"))
        assert isinstance(report, ResearchReport)
        assert report.sources == []


class TestDomainFiltering:
    """Tests for ResearcherAgent._filter_by_domain and _extract_domain."""

    def test_filter_allow_all_when_none(self):
        """allowed_domains=None allows all results through."""
        agent = ResearcherAgent(allowed_domains=None)
        results = [
            _make_source("A", "https://example.com/1", "S1"),
            _make_source("B", "https://other.org/2", "S2"),
        ]
        filtered = agent._filter_by_domain(results)
        assert len(filtered) == 2

    def test_filter_allow_all_when_empty_list(self):
        """allowed_domains=[] allows all results through."""
        agent = ResearcherAgent(allowed_domains=[])
        results = [
            _make_source("A", "https://example.com/1", "S1"),
        ]
        filtered = agent._filter_by_domain(results)
        assert len(filtered) == 1

    def test_filter_whitelist_matches_exact_domain(self):
        """allowed_domains=['example.com'] keeps example.com results."""
        agent = ResearcherAgent(allowed_domains=["example.com"])
        results = [
            _make_source("A", "https://example.com/1", "S1"),
            _make_source("B", "https://other.org/2", "S2"),
        ]
        filtered = agent._filter_by_domain(results)
        assert len(filtered) == 1
        assert filtered[0]["url"] == "https://example.com/1"

    def test_filter_whitelist_blocks_non_matching(self):
        """allowed_domains=['trusted.org'] filters out non-matching results."""
        agent = ResearcherAgent(allowed_domains=["trusted.org"])
        results = [
            _make_source("A", "https://evil.com/1", "Bad"),
            _make_source("B", "https://trusted.org/2", "Good"),
            _make_source("C", "https://other.net/3", "Other"),
        ]
        filtered = agent._filter_by_domain(results)
        assert len(filtered) == 1
        assert filtered[0]["url"] == "https://trusted.org/2"

    def test_filter_whitelist_matches_subdomain(self):
        """Subdomains should match the parent domain in the whitelist."""
        agent = ResearcherAgent(allowed_domains=["example.com"])
        results = [
            _make_source("A", "https://sub.example.com/page", "S1"),
        ]
        filtered = agent._filter_by_domain(results)
        assert len(filtered) == 1

    def test_filter_no_results_when_none_match(self):
        """If no results match the whitelist, return empty list."""
        agent = ResearcherAgent(allowed_domains=["only-this.org"])
        results = [
            _make_source("A", "https://other.com/1", "S1"),
        ]
        filtered = agent._filter_by_domain(results)
        assert filtered == []

    def test_extract_domain_simple(self):
        """_extract_domain('https://example.com/page') -> 'example.com'."""
        agent = ResearcherAgent()
        assert agent._extract_domain("https://example.com/page") == "example.com"

    def test_extract_domain_no_path(self):
        """_extract_domain handles URL with no path."""
        agent = ResearcherAgent()
        assert agent._extract_domain("https://example.com") == "example.com"

    def test_extract_domain_with_subdomain(self):
        """_extract_domain extracts subdomain hostname."""
        agent = ResearcherAgent()
        assert agent._extract_domain("https://sub.example.com/path") == "sub.example.com"

    def test_extract_domain_empty_string(self):
        """_extract_domain returns empty string for empty URL."""
        agent = ResearcherAgent()
        assert agent._extract_domain("") == ""

    def test_extract_domain_no_scheme(self):
        """_extract_domain handles URL with no scheme (urlparse may parse differently)."""
        agent = ResearcherAgent()
        # urlparse without scheme treats the whole string as a path,
        # so hostname is empty. This is expected behavior.
        domain = agent._extract_domain("example.com/page")
        # With no scheme, urlparse puts "example.com" as the path, hostname is empty
        assert domain == ""


class TestSynthesize:
    """Tests for ResearcherAgent._synthesize."""

    def test_synthesize_produces_summary(self):
        """Summary concatenates source snippets."""
        agent = ResearcherAgent()
        sources = [
            _make_source("T1", "https://a.com/1", "Snippet A"),
            _make_source("T2", "https://b.com/2", "Snippet B"),
        ]
        report = agent._synthesize("Test Q", sources)
        assert "Snippet A" in report.summary
        assert "Snippet B" in report.summary

    def test_synthesize_produces_claims(self):
        """Claims are extracted from source snippets."""
        agent = ResearcherAgent()
        sources = [
            _make_source("T1", "https://a.com/1", "First fact here. Another point there."),
        ]
        report = agent._synthesize("Test Q", sources)
        assert len(report.claims) >= 1
        assert report.claims[0]["source_url"] == "https://a.com/1"

    def test_synthesize_with_empty_sources(self):
        """Empty sources returns empty summary and claims — no crash."""
        agent = ResearcherAgent()
        report = agent._synthesize("Test Q", [])
        assert report.summary == ""
        assert report.claims == []
        assert report.confidence == 0.3

    def test_confidence_increases_with_more_sources(self):
        """More sources -> higher confidence."""
        agent = ResearcherAgent()
        few = [_make_source("T", "https://a.com/1", "S")]
        many = [
            _make_source(f"T{i}", f"https://a.com/{i}", f"S{i}")
            for i in range(5)
        ]
        report_few = agent._synthesize("Q", few)
        report_many = agent._synthesize("Q", many)
        assert report_many.confidence > report_few.confidence

    def test_confidence_capped_at_one(self):
        """Confidence never exceeds 1.0."""
        agent = ResearcherAgent()
        sources = [
            _make_source(f"T{i}", f"https://a.com/{i}", f"S{i}")
            for i in range(20)
        ]
        report = agent._synthesize("Q", sources)
        assert report.confidence <= 1.0

    def test_confidence_formula(self):
        """Confidence = min(1.0, 0.3 + len(sources) * 0.1)."""
        agent = ResearcherAgent()
        for n, expected in [(0, 0.3), (1, 0.4), (3, 0.6), (7, 1.0)]:
            sources = [_make_source(f"T{i}", f"https://a.com/{i}", f"S{i}") for i in range(n)]
            report = agent._synthesize("Q", sources)
            assert report.confidence == pytest.approx(expected), f"n={n}: expected {expected}, got {report.confidence}"

    def test_synthesize_handles_source_without_snippet(self):
        """Source with no snippet field should not crash."""
        agent = ResearcherAgent()
        sources = [
            {"title": "T1", "url": "https://a.com/1"},  # no snippet
        ]
        report = agent._synthesize("Q", sources)
        assert isinstance(report, ResearchReport)
        # Title should appear in summary even without snippet
        assert "T1" in report.summary


class TestCreateKnowledgeObject:
    """Tests for ResearcherAgent.create_knowledge_object()."""

    def _make_report(self, **overrides):
        """Create a minimal ResearchReport for testing create_knowledge_object."""
        now = int(time.time() * 1000)
        defaults = {
            "id": "research-abc123",
            "question": "What is Kafka?",
            "summary": "Kafka is a distributed streaming platform.",
            "sources": [
                {
                    "title": "Kafka Overview",
                    "url": "https://example.com/kafka",
                    "snippet": "Apache Kafka is a distributed streaming platform.",
                    "source_type": "web_search",
                    "search_url": "https://example.com/kafka",
                    "retrieved_at": now,
                }
            ],
            "confidence": 0.7,
            "claims": [
                {"text": "Kafka is a streaming platform.", "source_index": 0,
                 "source_url": "https://example.com/kafka", "source_title": "Kafka Overview"},
            ],
            "created_at": now,
        }
        defaults.update(overrides)
        return ResearchReport(**defaults)

    def test_lifecycle_is_processing(self):
        """KnowledgeObject lifecycle is PROCESSING (not ACTIVE)."""
        agent = ResearcherAgent()
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert obj.lifecycle == LifecycleState.PROCESSING

    def test_type_is_synthesis(self):
        """KnowledgeObject type is KnowledgeType.SYNTHESIS."""
        agent = ResearcherAgent()
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert obj.type == KnowledgeType.SYNTHESIS

    def test_title_matches_question(self):
        """KnowledgeObject title equals the research question."""
        agent = ResearcherAgent()
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert obj.title == "What is Kafka?"

    def test_provenance_includes_web_search_source(self):
        """Primary provenance reflects the first web search source."""
        agent = ResearcherAgent()
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert obj.provenance.source_path == "https://example.com/kafka"
        assert obj.provenance.ingestor_version == "web_search"
        assert "streaming" in obj.provenance.quote

    def test_relations_stores_all_sources(self):
        """All web sources are stored in the relations field."""
        agent = ResearcherAgent()
        report = self._make_report(sources=[
            {
                "title": "A", "url": "https://a.com/1", "snippet": "SA",
                "source_type": "web_search", "search_url": "https://a.com/1",
                "retrieved_at": int(time.time() * 1000),
            },
            {
                "title": "B", "url": "https://b.com/2", "snippet": "SB",
                "source_type": "web_search", "search_url": "https://b.com/2",
                "retrieved_at": int(time.time() * 1000),
            },
        ])
        obj = agent.create_knowledge_object(report)
        assert len(obj.relations) == 2
        assert obj.relations[0]["url"] == "https://a.com/1"
        assert obj.relations[1]["url"] == "https://b.com/2"
        for rel in obj.relations:
            assert rel["source_type"] == "web_search"

    def test_content_includes_summary_and_claims(self):
        """Content field contains the summary and claims sections."""
        agent = ResearcherAgent()
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert "What is Kafka?" in obj.content
        assert "distributed streaming platform" in obj.content
        assert "## Claims" in obj.content

    def test_empty_sources_no_crash(self):
        """Report with empty sources creates a valid KnowledgeObject."""
        agent = ResearcherAgent()
        report = self._make_report(sources=[], claims=[])
        obj = agent.create_knowledge_object(report)
        assert isinstance(obj, KnowledgeObject)
        assert obj.type == KnowledgeType.SYNTHESIS
        assert obj.lifecycle == LifecycleState.PROCESSING

    def test_provenance_tracker_called_when_available(self, tmp_path):
        """When provenance_tracker is set, record_derivation is called."""
        from unittest.mock import MagicMock

        tracker = MagicMock(spec=ProvenanceTracker)
        agent = ResearcherAgent(provenance_tracker=tracker)
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        tracker.record_derivation.assert_called()

    def test_provenance_tracker_exception_does_not_crash(self):
        """If provenance tracker raises, create_knowledge_object still succeeds."""
        from unittest.mock import MagicMock

        tracker = MagicMock(spec=ProvenanceTracker)
        tracker.record_derivation.side_effect = RuntimeError("Tracker down")
        agent = ResearcherAgent(provenance_tracker=tracker)
        report = self._make_report()
        obj = agent.create_knowledge_object(report)
        assert isinstance(obj, KnowledgeObject)
        assert obj.type == KnowledgeType.SYNTHESIS

    def test_confidence_propagated(self):
        """KnowledgeObject.confidence matches report.confidence."""
        agent = ResearcherAgent()
        report = self._make_report(confidence=0.85)
        obj = agent.create_knowledge_object(report)
        assert obj.confidence == 0.85


class TestResearchIntegration:
    """End-to-end research() -> create_knowledge_object() integration."""

    def test_full_flow_research_to_object(self):
        """Complete flow: research question -> ResearchReport -> KnowledgeObject."""
        mock = MockSearchProvider([
            _make_source("Kafka Docs", "https://kafka.apache.org/intro", "Apache Kafka is a distributed event streaming platform."),
            _make_source("Kafka Wiki", "https://en.wikipedia.org/wiki/Kafka", "Apache Kafka is an open-source distributed event streaming platform."),
        ])
        agent = ResearcherAgent(web_search_provider=mock)
        report = _run(agent.research("What is Apache Kafka?"))
        obj = agent.create_knowledge_object(report)

        # Verify the full chain
        assert isinstance(obj, KnowledgeObject)
        assert obj.type == KnowledgeType.SYNTHESIS
        assert obj.lifecycle == LifecycleState.PROCESSING
        assert obj.title == "What is Apache Kafka?"
        assert "Kafka" in obj.content
        assert obj.confidence > 0.3  # More than 0 sources -> confidence above baseline
        assert len(obj.relations) == 2
        for rel in obj.relations:
            assert rel["source_type"] == "web_search"

    def test_full_flow_with_domain_filter(self):
        """Full flow with domain whitelist filters sources before synthesis."""
        mock = MockSearchProvider([
            _make_source("Trusted", "https://trusted.org/article", "Useful information."),
            _make_source("Untrusted", "https://evil.com/article", "Misinformation."),
        ])
        agent = ResearcherAgent(web_search_provider=mock, allowed_domains=["trusted.org"])
        report = _run(agent.research("Test Q"))
        obj = agent.create_knowledge_object(report)

        assert len(report.sources) == 1
        assert report.sources[0]["url"] == "https://trusted.org/article"
        assert len(obj.relations) == 1
        assert obj.relations[0]["url"] == "https://trusted.org/article"

    def test_full_flow_no_search_provider(self):
        """Full flow with no search provider produces empty but valid object."""
        agent = ResearcherAgent(web_search_provider=None)
        report = _run(agent.research("Test Q"))
        obj = agent.create_knowledge_object(report)

        assert isinstance(obj, KnowledgeObject)
        assert obj.type == KnowledgeType.SYNTHESIS
        assert obj.lifecycle == LifecycleState.PROCESSING
        assert obj.sources == [] if hasattr(obj, 'sources') else True  # object is valid
