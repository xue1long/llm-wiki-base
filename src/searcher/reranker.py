# ruflo-kb/src/searcher/reranker.py
"""Post-retrieval result reranking.

When enabled, re-ranks fused results to improve relevance ordering.
When disabled (default in Phase 3), passes results through unchanged.

Two modes:
- score_fusion: Weighted combination of vector + keyword + graph scores
- llm: LLM-based relevance scoring (not implemented in Phase 3)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Source weights for score_fusion mode.
SOURCE_WEIGHTS: dict[str, float] = {
    "vector": 0.5,
    "keyword": 0.3,
    "graph": 0.2,
}

#: Bonus per additional source when same result appears in multiple sources.
SOURCE_DIVERSITY_BONUS: float = 0.1

#: Maximum boost from query term overlap.
MAX_OVERLAP_BOOST: float = 0.1


@dataclass
class RankedResult:
    """A single ranked search result."""

    object_id: str
    title: str
    content: str  # snippet or full content
    score: float  # 0.0 - 1.0 relevance score
    source: str  # "vector" | "keyword" | "graph"
    metadata: dict = field(default_factory=dict)


@dataclass
class RerankerConfig:
    """Configuration for the Reranker.

    Attributes:
        enabled: Whether reranking is active. Default False (Phase 3).
        method: Reranking method — "score_fusion" | "llm" | "cross_encoder".
    """

    enabled: bool = False
    method: str = "score_fusion"


class Reranker:
    """Post-retrieval result reranking.

    When enabled, re-ranks fused results to improve relevance ordering.
    When disabled (default in Phase 3), passes results through unchanged.

    Two modes:
    - score_fusion: Weighted combination of vector + keyword scores
    - llm: LLM-based relevance scoring (not implemented, falls back to score_fusion)
    """

    def __init__(self, config: RerankerConfig | None = None):
        self.config = config or RerankerConfig()

    def rerank(
        self, results: list[RankedResult], query: str
    ) -> list[RankedResult]:
        """Rerank results by relevance to query.

        When disabled: return results unchanged (fallback path).
        When score_fusion: combine scores from different sources with weights.
        When llm: use LLM to score each result (not implemented in Phase 3,
        falls back to score_fusion).
        """
        if not self.config.enabled:
            return results

        method = self.config.method

        if method == "llm":
            logger.warning(
                "Reranker: llm method not implemented; falling back to score_fusion"
            )
            return self._score_fusion(results, query)

        if method == "score_fusion":
            return self._score_fusion(results, query)

        # Unknown method — pass through
        logger.warning(
            "Reranker: unknown method %r; passing results through unchanged",
            method,
        )
        return results

    def _score_fusion(
        self, results: list[RankedResult], query: str
    ) -> list[RankedResult]:
        """Weighted score fusion.

        - Vector results: weight 0.5
        - Keyword results: weight 0.3
        - Graph results: weight 0.2

        Compute overlap bonus: if same result appears in multiple sources,
        boost score by 0.1 per additional source.
        """
        if not results:
            return []

        # Step 1: Deduplicate by object_id, keeping the highest score
        # per source and tracking which sources each object_id appears in.
        best_by_src: dict[tuple[str, str], RankedResult] = {}
        for r in results:
            key = (r.object_id, r.source)
            if key not in best_by_src or r.score > best_by_src[key].score:
                best_by_src[key] = r

        # Group by object_id: collect sources and the best result per id.
        by_id: dict[str, dict] = {}
        for (obj_id, src), r in best_by_src.items():
            if obj_id not in by_id:
                by_id[obj_id] = {
                    "best": r,
                    "sources": {src},
                    "max_score": r.score,
                }
            else:
                entry = by_id[obj_id]
                entry["sources"].add(src)
                if r.score > entry["max_score"]:
                    entry["max_score"] = r.score
                    entry["best"] = r

        # Step 2: Compute composite scores.
        scored: list[RankedResult] = []
        for obj_id, entry in by_id.items():
            best = entry["best"]
            sources = entry["sources"]

            # Base weighted score
            base_score = 0.0
            for src in sources:
                weight = SOURCE_WEIGHTS.get(src, 0.0)
                base_score += best.score * weight

            # Source diversity bonus
            diversity = SOURCE_DIVERSITY_BONUS * (len(sources) - 1)

            composite = base_score + diversity
            # Clamp to [0, 1]
            composite = max(0.0, min(1.0, composite))

            scored.append(RankedResult(
                object_id=obj_id,
                title=best.title,
                content=best.content,
                score=composite,
                source=",".join(sorted(sources)),
                metadata=best.metadata,
            ))

        # Step 3: Apply query overlap boost.
        scored = self._boost_by_query_overlap(scored, query)

        # Step 4: Sort by score descending.
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    def _boost_by_query_overlap(
        self, results: list[RankedResult], query: str
    ) -> list[RankedResult]:
        """Simple TF-ish boost: count query term occurrences in content,
        add up to 0.1 bonus.

        Splits query into lowercase terms. For each result, counts how many
        query terms appear in title+content (case-insensitive). Normalizes
        to a 0-0.1 bonus proportional to the fraction of query terms matched.
        """
        if not results or not query.strip():
            return results

        query_terms = query.lower().split()
        if not query_terms:
            return results

        for r in results:
            text = (r.title + " " + r.content).lower()
            matches = sum(1 for term in query_terms if term in text)
            fraction = matches / len(query_terms)
            boost = fraction * MAX_OVERLAP_BOOST
            r.score = max(0.0, min(1.0, r.score + boost))

        return results
