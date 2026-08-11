"""Tests for QueryUnderstanding — query classification, entity extraction,
intent detection, and memory type routing.
"""

import pytest

from src.searcher.query_understanding import (
    QueryType,
    QueryIntent,
    QueryUnderstanding,
    MEMORY_SEMANTIC,
    MEMORY_EPISODIC,
    MEMORY_DECISION,
    MEMORY_PROCEDURAL,
)


@pytest.fixture
def q():
    """Reusable QueryUnderstanding instance."""
    return QueryUnderstanding()


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassification:
    def test_factoid_what(self, q):
        result = q.understand("What is Kafka?")
        assert result.type == QueryType.FACTOID

    def test_factoid_who(self, q):
        result = q.understand("Who created Kafka?")
        assert result.type == QueryType.FACTOID

    def test_factoid_when(self, q):
        result = q.understand("When was Kafka released?")
        assert result.type == QueryType.FACTOID

    def test_factoid_where(self, q):
        result = q.understand("Where is Kafka used?")
        assert result.type == QueryType.FACTOID

    def test_factoid_which(self, q):
        result = q.understand("Which version of Kafka?")
        assert result.type == QueryType.FACTOID

    def test_explanatory_how(self, q):
        result = q.understand("How does Kafka work?")
        assert result.type == QueryType.EXPLANATORY

    def test_explanatory_why(self, q):
        result = q.understand("Why Kafka is fast?")
        assert result.type == QueryType.EXPLANATORY

    def test_procedural_how_to(self, q):
        result = q.understand("How to configure Kafka?")
        assert result.type == QueryType.PROCEDURAL

    def test_procedural_steps_to(self, q):
        result = q.understand("steps to deploy Kafka")
        assert result.type == QueryType.PROCEDURAL

    def test_decision_context(self, q):
        result = q.understand("Why did we choose Kafka?")
        assert result.type == QueryType.DECISION_CONTEXT

    def test_decision_context_keyword(self, q):
        result = q.understand("decision about Kafka")
        assert result.type == QueryType.DECISION_CONTEXT


# ---------------------------------------------------------------------------
# Entity extraction tests
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    def test_extracts_capitalized_phrase(self, q):
        result = q.understand("What is Apache Kafka?")
        assert "Apache Kafka" in result.entities

    def test_extracts_quoted_phrase(self, q):
        result = q.understand('"exactly once" semantics')
        assert "exactly once" in result.entities

    def test_extracts_multiple_capitalized(self, q):
        result = q.understand("How does Amazon Web Services compare to Google Cloud Platform?")
        assert "Amazon Web Services" in result.entities
        assert "Google Cloud Platform" in result.entities

    def test_no_entities_in_simple_query(self, q):
        result = q.understand("how does it work")
        assert result.entities == []

    def test_single_capitalized_word(self, q):
        result = q.understand("Tell me about Kafka")
        assert "Kafka" in result.entities


# ---------------------------------------------------------------------------
# Memory type routing tests
# ---------------------------------------------------------------------------

class TestMemoryTypeRouting:
    def test_factoid_routing(self, q):
        result = q.understand("What is Kafka?")
        assert result.target_memory_types == [MEMORY_SEMANTIC]

    def test_explanatory_routing(self, q):
        result = q.understand("How does Kafka work?")
        assert result.target_memory_types == [MEMORY_SEMANTIC, MEMORY_EPISODIC]

    def test_procedural_routing(self, q):
        result = q.understand("How to configure Kafka?")
        assert result.target_memory_types == [MEMORY_PROCEDURAL]

    def test_decision_routing(self, q):
        result = q.understand("Why did we choose Kafka?")
        assert result.target_memory_types == [MEMORY_DECISION]


# ---------------------------------------------------------------------------
# Intent detection tests
# ---------------------------------------------------------------------------

class TestIntentDetection:
    def test_default_is_search(self, q):
        result = q.understand("Kafka configuration")
        assert result.intent == QueryIntent.SEARCH

    def test_recall_keyword(self, q):
        result = q.understand("recall object abc123")
        assert result.intent == QueryIntent.RECALL

    def test_verify_keyword(self, q):
        result = q.understand("verify that Kafka supports exactly-once")
        assert result.intent == QueryIntent.VERIFY

    def test_verify_is_it_true(self, q):
        result = q.understand("is it true that Kafka is written in Scala")
        assert result.intent == QueryIntent.VERIFY

    def test_explain_intent(self, q):
        result = q.understand("explain why Kafka uses ZooKeeper")
        assert result.intent == QueryIntent.EXPLAIN


# ---------------------------------------------------------------------------
# UnderstoodQuery structure tests
# ---------------------------------------------------------------------------

class TestUnderstoodQueryStructure:
    def test_all_fields_populated(self, q):
        result = q.understand("What is Apache Kafka?")
        assert result.original == "What is Apache Kafka?"
        assert result.type == QueryType.FACTOID
        assert isinstance(result.intent, QueryIntent)
        assert isinstance(result.expanded_terms, list)
        assert isinstance(result.target_memory_types, list)
        assert isinstance(result.entities, list)
        assert result.confidence > 0.0

    def test_entities_in_expanded_terms(self, q):
        result = q.understand("What is Apache Kafka?")
        for entity in result.entities:
            assert entity in result.expanded_terms


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_query_no_crash(self, q):
        result = q.understand("")
        assert result.original == ""
        assert result.type == QueryType.FACTOID
        assert result.intent == QueryIntent.SEARCH
        assert result.entities == []
        assert result.confidence == 0.0

    def test_whitespace_only_query(self, q):
        result = q.understand("   \t\n  ")
        assert result.type == QueryType.FACTOID
        assert result.confidence == 0.0

    def test_single_word_query(self, q):
        result = q.understand("Kafka")
        assert result.type == QueryType.FACTOID
        assert result.entities == ["Kafka"]  # single capitalized word matches entity pattern
        assert result.intent == QueryIntent.SEARCH

    def test_short_query_defaults(self, q):
        result = q.understand("help")
        assert result.type == QueryType.FACTOID
        assert result.intent == QueryIntent.SEARCH
