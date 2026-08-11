"""Test MemoryRetrieval orchestrator (Task 3.6)."""

from src.knowledge.memory.retrieval import MemoryResponse, MemoryRetrieval
from src.searcher.query_understanding import QueryType
from src.searcher.reranker import RankedResult, Reranker, RerankerConfig


# ---------------------------------------------------------------------------
# MemoryResponse dataclass tests
# ---------------------------------------------------------------------------


class TestMemoryResponseDataclass:
    """MemoryResponse fields and defaults."""

    def test_default_construction(self):
        """All fields have sensible defaults."""
        mr = MemoryResponse()
        assert mr.memory_object is None
        assert mr.provenance_chain is None
        assert mr.related_decisions == []
        assert mr.conflicting_claims == []
        assert mr.ranked_results == []
        assert mr.query == ""
        assert mr.query_type == ""

    def test_full_construction(self):
        """All fields can be set explicitly."""
        mr = MemoryResponse(
            memory_object={"id": "x"},
            provenance_chain={"source_path": "/a"},
            related_decisions=[{"id": "d1"}],
            conflicting_claims=[{"claim_a": "c1"}],
            ranked_results=[{"path": "p"}],
            query="hello",
            query_type="factoid",
        )
        assert mr.memory_object == {"id": "x"}
        assert mr.provenance_chain == {"source_path": "/a"}
        assert mr.related_decisions == [{"id": "d1"}]
        assert mr.conflicting_claims == [{"claim_a": "c1"}]
        assert mr.ranked_results == [{"path": "p"}]
        assert mr.query == "hello"
        assert mr.query_type == "factoid"

    def test_is_dataclass(self):
        """MemoryResponse is a dataclass, not a plain class."""
        from dataclasses import is_dataclass
        assert is_dataclass(MemoryResponse)


# ---------------------------------------------------------------------------
# MemoryRetrieval.retrieve() tests
# ---------------------------------------------------------------------------


class TestRetrieveBasic:
    """Basic retrieve() behaviour."""

    def test_returns_memory_response(self):
        """retrieve() returns a MemoryResponse instance."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("What is Kafka?")
        assert isinstance(resp, MemoryResponse)

    def test_query_preserved(self):
        """The original query is preserved in the response."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("What is Kafka?")
        assert resp.query == "What is Kafka?"

    def test_query_type_is_set(self):
        """Response.query_type matches one of the known QueryType values."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("What is Kafka?")
        valid = {qt.value for qt in QueryType}
        assert resp.query_type in valid, (
            f"query_type {resp.query_type!r} not in {valid}"
        )

    def test_factoid_query_type(self):
        """'What is X' queries classify as factoid."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("What is Kafka?")
        assert resp.query_type == "factoid"


class TestRetrieveNoSearcher:
    """Graceful degradation when no searcher is injected."""

    def test_empty_results_no_crash(self):
        """Without searcher, ranked_results is empty but no crash."""
        mr = MemoryRetrieval()  # no searcher
        resp = mr.retrieve("anything at all")
        assert resp.ranked_results == []
        assert resp.memory_object is None

    def test_response_still_valid(self):
        """Response fields are still sensible without searcher."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("test query")
        assert isinstance(resp, MemoryResponse)
        assert resp.query == "test query"
        assert resp.query_type != ""


class TestRetrieveWithMockSearcher:
    """retrieve() with a mock searcher injected."""

    def test_mock_results_appear_in_response(self):
        """Mock searcher results appear in ranked_results."""
        mock_results = [
            {"path": "wiki/concepts/kafka.md", "title": "Kafka", "content": "Apache Kafka is...", "score": 0.9, "source": "vector"},
        ]
        mr = MemoryRetrieval(searcher=lambda q, **kw: mock_results)
        resp = mr.retrieve("Kafka")
        assert len(resp.ranked_results) > 0, "Expected non-empty ranked_results"

    def test_mock_results_content(self):
        """Result title and content flow through."""
        mock_results = [
            {"path": "wiki/concepts/kafka.md", "title": "Apache Kafka", "content": "A distributed streaming platform", "score": 0.95, "source": "vector"},
        ]
        mr = MemoryRetrieval(searcher=lambda q, **kw: mock_results)
        resp = mr.retrieve("Kafka")
        top = resp.ranked_results[0]
        assert top.title == "Apache Kafka"
        assert "streaming" in top.content.lower()

    def test_top_result_becomes_memory_object(self):
        """The top-ranked result populates memory_object."""
        mock_results = [
            {"path": "wiki/a.md", "title": "A", "content": "Content A", "score": 0.9, "source": "vector"},
        ]
        mr = MemoryRetrieval(searcher=lambda q, **kw: mock_results)
        resp = mr.retrieve("A")
        assert resp.memory_object is not None
        assert resp.memory_object["title"] == "A"

    def test_empty_searcher_results(self):
        """Empty searcher results produce empty response."""
        mr = MemoryRetrieval(searcher=lambda q, **kw: [])
        resp = mr.retrieve("query")
        assert resp.ranked_results == []
        assert resp.memory_object is None

    def test_searcher_receives_memory_types(self):
        """The searcher receives the target memory_types from query classification."""
        captured = []

        def capturing_searcher(query, **kw):
            captured.append(kw)
            return []

        mr = MemoryRetrieval(searcher=capturing_searcher)
        mr.retrieve("How to install Python")
        assert len(captured) == 1
        assert "memory_types" in captured[0]
        # "How to install Python" -> "how to" prefix -> PROCEDURAL
        assert captured[0]["memory_types"] == ["procedural"]


class TestRetrieveReranker:
    """Reranker integration with retrieve()."""

    def test_disabled_reranker_passthrough(self):
        """Default Reranker (disabled) passes results through unchanged."""
        mock_results = [
            {"path": "wiki/x.md", "title": "X", "content": "X content", "score": 0.8, "source": "vector"},
        ]
        mr = MemoryRetrieval(
            searcher=lambda q, **kw: mock_results,
            reranker=Reranker(RerankerConfig(enabled=False)),
        )
        resp = mr.retrieve("X")
        assert len(resp.ranked_results) == 1
        assert resp.ranked_results[0].title == "X"
        assert resp.ranked_results[0].score == 0.8

    def test_enabled_score_fusion_reranker(self):
        """Score fusion reranker processes results."""
        mock_results = [
            {"path": "wiki/x.md", "title": "X", "content": "X content", "score": 0.8, "source": "vector"},
        ]
        mr = MemoryRetrieval(
            searcher=lambda q, **kw: mock_results,
            reranker=Reranker(RerankerConfig(enabled=True, method="score_fusion")),
        )
        resp = mr.retrieve("X")
        assert len(resp.ranked_results) == 1
        # Score may differ after fusion

    def test_reranker_receives_query(self):
        """Reranker sees the original query string."""
        mock_results = [
            {"path": "wiki/x.md", "title": "X", "content": "X content", "score": 0.8, "source": "vector"},
        ]

        class SpyReranker:
            def rerank(self, results, query):
                self.last_query = query
                return results

        spy = SpyReranker()
        mr = MemoryRetrieval(
            searcher=lambda q, **kw: mock_results,
            reranker=spy,
        )
        mr.retrieve("hello world")
        assert spy.last_query == "hello world"


# ---------------------------------------------------------------------------
# MemoryRetrieval.recall() tests
# ---------------------------------------------------------------------------


class TestRecall:
    """recall() behaviour."""

    def test_returns_memory_response(self):
        """recall() returns a MemoryResponse."""
        mr = MemoryRetrieval()
        resp = mr.recall("some-id")
        assert isinstance(resp, MemoryResponse)

    def test_query_type_is_recall(self):
        """recall() always sets query_type to 'recall'."""
        mr = MemoryRetrieval()
        resp = mr.recall("some-id")
        assert resp.query_type == "recall"

    def test_query_is_object_id(self):
        """The object_id becomes the query field."""
        mr = MemoryRetrieval()
        resp = mr.recall("my-object-42")
        assert resp.query == "my-object-42"

    def test_nonexistent_returns_none_object(self):
        """recall() of nonexistent ID returns memory_object=None (no crash)."""
        mr = MemoryRetrieval()  # no searcher
        resp = mr.recall("nonexistent-id")
        assert resp.memory_object is None
        assert resp.provenance_chain is None
        assert resp.related_decisions == []

    def test_with_mock_searcher(self):
        """recall() loads object via searcher when available."""
        mock_result = [{"path": "wiki/decisions/d1.md", "title": "Decision 1", "content": "We chose X", "score": 1.0, "source": "keyword"}]
        mr = MemoryRetrieval(searcher=lambda q, **kw: mock_result)
        resp = mr.recall("d1")
        assert resp.memory_object is not None
        assert resp.memory_object["title"] == "Decision 1"

    def test_with_provenance_tracker(self):
        """recall() populates provenance_chain when tracker is injected."""
        mock_result = [{"path": "wiki/entities/e1.md", "title": "Entity E", "content": "E content", "score": 1.0, "source": "keyword"}]

        class MockProvenanceTracker:
            def get_provenance_chain(self, object_id):
                return {"source_path": "/raw/e1.pdf", "derived_from": "/raw/e1.pdf", "derived_objects": ["e1"], "source_status": "active"}

        mr = MemoryRetrieval(
            searcher=lambda q, **kw: mock_result,
            provenance_tracker=MockProvenanceTracker(),
        )
        resp = mr.recall("e1")
        assert resp.provenance_chain is not None
        assert resp.provenance_chain["source_path"] == "/raw/e1.pdf"
        assert resp.provenance_chain["source_status"] == "active"

    def test_with_decision_recorder(self):
        """recall() populates related_decisions when recorder is injected."""
        mock_result = [{"path": "wiki/decisions/d1.md", "title": "Decision", "content": "X", "score": 1.0, "source": "keyword"}]

        class MockDecisionRecorder:
            def get_decision_context(self, decision_id):
                return {"id": decision_id, "question": "What?", "decision": "X", "context": "background", "alternatives": [], "rationale": "best option", "outcome": "", "actual_impact": ""}

        mr = MemoryRetrieval(
            searcher=lambda q, **kw: mock_result,
            decision_recorder=MockDecisionRecorder(),
        )
        resp = mr.recall("d1")
        assert len(resp.related_decisions) == 1
        assert resp.related_decisions[0]["id"] == "d1"

    def test_provenance_errors_graceful(self):
        """ProvenanceTracker errors don't crash recall()."""
        class BrokenProvenanceTracker:
            def get_provenance_chain(self, object_id):
                raise RuntimeError("database down")

        mr = MemoryRetrieval(provenance_tracker=BrokenProvenanceTracker())
        resp = mr.recall("some-id")
        assert resp.provenance_chain is None
        assert isinstance(resp, MemoryResponse)

    def test_searcher_errors_graceful(self):
        """Searcher errors don't crash recall()."""
        def broken_searcher(query, **kw):
            raise RuntimeError("search failed")

        mr = MemoryRetrieval(searcher=broken_searcher)
        resp = mr.recall("some-id")
        assert resp.memory_object is None
        assert isinstance(resp, MemoryResponse)

    def test_decision_errors_graceful(self):
        """DecisionRecorder errors don't crash recall()."""
        class BrokenDecisionRecorder:
            def get_decision_context(self, decision_id):
                raise RuntimeError("db down")

        mr = MemoryRetrieval(decision_recorder=BrokenDecisionRecorder())
        resp = mr.recall("some-id")
        assert resp.related_decisions == []


# ---------------------------------------------------------------------------
# _assemble_response tests
# ---------------------------------------------------------------------------


class TestAssembleResponse:
    """Internal _assemble_response structure tests."""

    def test_structure_no_results(self):
        """No results -> all enrichment fields empty."""
        from src.searcher.query_understanding import QueryUnderstanding
        qu = QueryUnderstanding()
        understood = qu.understand("test")

        mr = MemoryRetrieval()
        resp = mr._assemble_response("test", understood, [], None)
        assert resp.memory_object is None
        assert resp.provenance_chain is None
        assert resp.related_decisions == []
        assert resp.conflicting_claims == []
        assert resp.ranked_results == []
        assert resp.query == "test"
        assert resp.query_type == understood.type.value

    def test_structure_with_top_result(self):
        """Top result populates memory_object."""
        from src.searcher.query_understanding import QueryUnderstanding
        qu = QueryUnderstanding()
        understood = qu.understand("test")

        top = RankedResult(
            object_id="wiki/x.md",
            title="Title X",
            content="Content X",
            score=0.95,
            source="vector",
        )

        mr = MemoryRetrieval()
        resp = mr._assemble_response("test", understood, [top], top)
        assert resp.memory_object is not None
        assert resp.memory_object["title"] == "Title X"
        assert resp.memory_object["object_id"] == "wiki/x.md"

    def test_query_type_value_preserved(self):
        """query_type comes from UnderstoodQuery.type.value."""
        from src.searcher.query_understanding import QueryUnderstanding
        qu = QueryUnderstanding()
        understood = qu.understand("Why is the sky blue?")

        mr = MemoryRetrieval()
        resp = mr._assemble_response("Why is the sky blue?", understood, [], None)
        assert resp.query_type == "explanatory"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """All optional components as None — still works."""

    def test_no_components_retrieve(self):
        """retrieve() works with zero injected dependencies."""
        mr = MemoryRetrieval(
            searcher=None,
            reranker=None,
            provenance_tracker=None,
            conflict_detector=None,
            decision_recorder=None,
        )
        resp = mr.retrieve("test query")
        assert isinstance(resp, MemoryResponse)
        assert resp.query == "test query"
        assert resp.ranked_results == []

    def test_no_components_recall(self):
        """recall() works with zero injected dependencies."""
        mr = MemoryRetrieval(
            searcher=None,
            reranker=None,
            provenance_tracker=None,
            conflict_detector=None,
            decision_recorder=None,
        )
        resp = mr.recall("object-1")
        assert isinstance(resp, MemoryResponse)
        assert resp.query == "object-1"
        assert resp.memory_object is None

    def test_default_reranker_still_works(self):
        """Default Reranker (enabled=False) is created when reranker=None."""
        mr = MemoryRetrieval(reranker=None)
        resp = mr.retrieve("anything")
        assert isinstance(resp, MemoryResponse)


# ---------------------------------------------------------------------------
# Query type routing tests
# ---------------------------------------------------------------------------


class TestQueryTypeRouting:
    """Different query types route to correct memory types."""

    def test_factoid_routes_to_semantic(self):
        """Factoid questions target SEMANTIC memory."""
        captured = []
        mr = MemoryRetrieval(searcher=lambda q, **kw: captured.append(kw) or [])
        mr.retrieve("What is Kafka?")
        assert captured[0]["memory_types"] == ["semantic"]

    def test_explanatory_routes_to_semantic_episodic(self):
        """Explanatory questions target SEMANTIC + EPISODIC memory."""
        captured = []
        mr = MemoryRetrieval(searcher=lambda q, **kw: captured.append(kw) or [])
        mr.retrieve("Why does the sky appear blue?")
        assert captured[0]["memory_types"] == ["semantic", "episodic"]

    def test_procedural_routes_to_procedural(self):
        """Procedural questions target PROCEDURAL memory."""
        captured = []
        mr = MemoryRetrieval(searcher=lambda q, **kw: captured.append(kw) or [])
        mr.retrieve("How to install Python on Windows?")
        assert captured[0]["memory_types"] == ["procedural"]

    def test_decision_routes_to_decision(self):
        """Decision questions target DECISION memory."""
        captured = []
        mr = MemoryRetrieval(searcher=lambda q, **kw: captured.append(kw) or [])
        mr.retrieve("Why did we choose Kafka over RabbitMQ?")
        assert captured[0]["memory_types"] == ["decision"]

    def test_empty_query_handled(self):
        """Empty or whitespace query is handled gracefully."""
        mr = MemoryRetrieval()
        resp = mr.retrieve("")
        assert isinstance(resp, MemoryResponse)
        assert resp.query == ""


# ---------------------------------------------------------------------------
# _search_by_memory_types tests
# ---------------------------------------------------------------------------


class TestSearchByMemoryTypes:
    """Direct tests for _search_by_memory_types."""

    def test_no_searcher_returns_empty(self):
        """Without searcher, returns empty list."""
        mr = MemoryRetrieval()
        result = mr._search_by_memory_types("test", ["semantic"])
        assert result == []

    def test_searcher_called_with_memory_types(self):
        """Searcher receives memory_types kwarg."""
        captured = []

        def spy(q, **kw):
            captured.append((q, kw))
            return [{"path": "x", "title": "X", "content": "c", "score": 0.5, "source": "kw"}]

        mr = MemoryRetrieval(searcher=spy)
        result = mr._search_by_memory_types("hello", ["semantic", "episodic"])
        assert len(result) == 1
        assert captured[0][0] == "hello"
        assert captured[0][1]["memory_types"] == ["semantic", "episodic"]

    def test_searcher_exception_returns_empty(self):
        """Searcher exceptions are caught, returning []."""
        def failing(q, **kw):
            raise RuntimeError("boom")

        mr = MemoryRetrieval(searcher=failing)
        result = mr._search_by_memory_types("test", ["semantic"])
        assert result == []

    def test_searcher_returns_none_treated_as_empty(self):
        """Searcher returning None is treated as empty."""
        mr = MemoryRetrieval(searcher=lambda q, **kw: None)
        result = mr._search_by_memory_types("test", ["semantic"])
        assert result == []
