"""Pre-search query classification and expansion.

Routes queries to the appropriate memory type.
Expands queries with entity recognition.
No LLM required — uses keyword/pattern heuristics.
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class QueryType(str, Enum):
    FACTOID = "factoid"
    EXPLANATORY = "explanatory"
    PROCEDURAL = "procedural"
    DECISION_CONTEXT = "decision_context"


class QueryIntent(str, Enum):
    SEARCH = "search"
    RECALL = "recall"
    VERIFY = "verify"
    EXPLAIN = "explain"


# Memory type string constants matching src.knowledge.memory.types.MemoryType
MEMORY_SEMANTIC = "semantic"
MEMORY_EPISODIC = "episodic"
MEMORY_DECISION = "decision"
MEMORY_PROCEDURAL = "procedural"


@dataclass
class UnderstoodQuery:
    """Result of query understanding: classification, entities, and routing."""

    original: str
    type: QueryType
    intent: QueryIntent
    expanded_terms: list[str] = field(default_factory=list)
    target_memory_types: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 1.0


class QueryUnderstanding:
    """Pre-search query classification and expansion.

    Routes queries to the appropriate memory type.
    Expands queries with entity recognition.
    """

    # Patterns for query type classification
    _FACTOID_PREFIXES = ("what", "who", "when", "where", "which")
    _EXPLANATORY_PREFIXES = ("how", "why")
    _EXPLANATORY_KEYWORDS = ("explain", "explanation")
    _PROCEDURAL_PREFIXES = ("how to", "steps to", "guide", "tutorial")
    _DECISION_KEYWORDS = ("choose", "chose", "chosen", "decide", "decision",
                          "why did we", "why we chose", "why we decided")

    # Patterns for intent detection
    _RECALL_KEYWORDS = ("recall", "show me the", "retrieve", "look up", "find the")
    _VERIFY_KEYWORDS = ("verify", "check", "is it true", "confirm", "validate",
                        "fact-check")
    _EXPLAIN_KEYWORDS = ("why", "explain", "reason", "reasoning")

    # Entity extraction patterns
    _QUOTED_PATTERN = re.compile(r'"([^"]+)"|“([^”]+)”')
    _CAPITALIZED_SEQUENCE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')

    # Word boundary for single capitalized words (2+ chars)
    _CAPITALIZED_WORD = re.compile(r'\b([A-Z][a-z]{1,})\b')

    # Stop words to avoid extracting as entities
    _STOP_WORDS = frozenset({
        "how", "what", "why", "when", "where", "who", "which",
        "explain", "describe", "define", "tell", "show",
        "choose", "chose", "chosen", "decide", "decision",
        "verify", "check", "confirm", "validate",
        "recall", "retrieve", "look", "find",
        "steps", "guide", "tutorial",
        "does", "would", "could", "should", "will", "can",
        "the", "and", "but", "for", "with", "from", "that", "this",
        "about", "between", "through", "during",
        "true", "false",
    })

    def understand(self, query: str) -> UnderstoodQuery:
        """Classify query and determine search strategy.

        Args:
            query: Raw user query string.

        Returns:
            UnderstoodQuery with classification, entities, and routing.
        """
        original = query
        query_lower = query.strip().lower()

        # Handle empty / whitespace-only queries
        if not query_lower:
            return UnderstoodQuery(
                original=original,
                type=QueryType.FACTOID,
                intent=QueryIntent.SEARCH,
                expanded_terms=[],
                target_memory_types=[MEMORY_SEMANTIC],
                entities=[],
                confidence=0.0,
            )

        query_type, confidence = self._classify(query_lower)
        intent = self._detect_intent(query_lower)
        entities = self._extract_entities(query)
        memory_types = self._determine_memory_types(query_type)

        # Build expanded terms: entities + meaningful tokens
        expanded = list(entities)

        return UnderstoodQuery(
            original=original,
            type=query_type,
            intent=intent,
            expanded_terms=expanded,
            target_memory_types=memory_types,
            entities=entities,
            confidence=confidence,
        )

    def _classify(self, query: str) -> tuple[QueryType, float]:
        """Classify query into one of the 4 types using keyword heuristics.

        Args:
            query: Lowercased, stripped query string.

        Returns:
            (QueryType, confidence) tuple.
        """
        # Procedural first (how to...)
        if any(query.startswith(p) for p in self._PROCEDURAL_PREFIXES):
            return QueryType.PROCEDURAL, 0.9

        # Decision context
        if any(kw in query for kw in self._DECISION_KEYWORDS):
            return QueryType.DECISION_CONTEXT, 0.9

        # Explanatory ("how does X work?" or "why X")
        if any(query.startswith(p) for p in self._EXPLANATORY_PREFIXES):
            # Distinguish "how to" (procedural) from "how does" (explanatory)
            if query.startswith("how to"):
                return QueryType.PROCEDURAL, 0.9
            return QueryType.EXPLANATORY, 0.85

        # Factoid
        if any(query.startswith(p) for p in self._FACTOID_PREFIXES):
            return QueryType.FACTOID, 0.9

        # Fallback heuristics based on keyword presence
        if any(kw in query for kw in self._EXPLANATORY_KEYWORDS):
            return QueryType.EXPLANATORY, 0.7

        # Default: treat as factoid lookup
        return QueryType.FACTOID, 0.5

    def _detect_intent(self, query: str) -> QueryIntent:
        """Detect query intent from keyword patterns.

        Args:
            query: Lowercased, stripped query string.

        Returns:
            QueryIntent classification.
        """
        # Recall: specific object lookup
        if any(kw in query for kw in self._RECALL_KEYWORDS):
            return QueryIntent.RECALL

        # Verify: fact checking
        if any(kw in query for kw in self._VERIFY_KEYWORDS):
            return QueryIntent.VERIFY

        # Explain: reasoning inquiry
        if any(kw in query for kw in self._EXPLAIN_KEYWORDS):
            return QueryIntent.EXPLAIN

        return QueryIntent.SEARCH

    def _extract_entities(self, query: str) -> list[str]:
        """Extract potential entity names from query.

        Simple approach: extract quoted phrases, capitalized multi-word
        sequences, and individual capitalized words, filtering out stop words.

        Args:
            query: Original (unlowered) query string.

        Returns:
            List of extracted entity strings.
        """
        entities: list[str] = []
        seen: set[str] = set()

        # 1) Quoted phrases (highest priority)
        for match in self._QUOTED_PATTERN.finditer(query):
            phrase = match.group(1) or match.group(2)
            if phrase and phrase.lower() not in self._STOP_WORDS:
                if phrase.lower() not in seen:
                    entities.append(phrase)
                    seen.add(phrase.lower())

        # 2) Multi-word capitalized sequences (e.g., "Apache Kafka")
        for match in self._CAPITALIZED_SEQUENCE.finditer(query):
            phrase = match.group(1)
            if phrase.lower() not in self._STOP_WORDS:
                if phrase.lower() not in seen:
                    entities.append(phrase)
                    seen.add(phrase.lower())

        # 3) Individual capitalized words
        for match in self._CAPITALIZED_WORD.finditer(query):
            word = match.group(1)
            if word.lower() not in self._STOP_WORDS:
                if word.lower() not in seen:
                    entities.append(word)
                    seen.add(word.lower())

        return entities

    def _determine_memory_types(self, query_type: QueryType) -> list[str]:
        """Map query type to relevant memory types.

        Args:
            query_type: The classified QueryType.

        Returns:
            List of memory type strings.
        """
        if query_type == QueryType.FACTOID:
            return [MEMORY_SEMANTIC]
        elif query_type == QueryType.EXPLANATORY:
            return [MEMORY_SEMANTIC, MEMORY_EPISODIC]
        elif query_type == QueryType.PROCEDURAL:
            return [MEMORY_PROCEDURAL]
        elif query_type == QueryType.DECISION_CONTEXT:
            return [MEMORY_DECISION]
        else:
            return [MEMORY_SEMANTIC]


# Singleton instance for convenience
query_understanding = QueryUnderstanding()
