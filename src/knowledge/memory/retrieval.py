"""MemoryRetrieval — orchestrator for the memory search pipeline.

Delegates to:
- QueryUnderstanding for query classification
- External searcher for vector/keyword/graph search (injected)
- Reranker for post-retrieval ranking
- ProvenanceTracker for provenance chains
- ConflictDetector for conflicting claims
- DecisionRecorder for decision context

All optional components degrade gracefully when None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.searcher.query_understanding import QueryUnderstanding, UnderstoodQuery
from src.searcher.reranker import RankedResult, Reranker


# ---------------------------------------------------------------------------
# MemoryResponse — the assembled output of a retrieval operation
# ---------------------------------------------------------------------------


@dataclass
class MemoryResponse:
    """Assembled response from memory retrieval."""

    memory_object: dict | None = None     # The primary retrieved object
    provenance_chain: dict | None = None  # Provenance data (from ProvenanceTracker)
    related_decisions: list[dict] = field(default_factory=list)  # Related decisions
    conflicting_claims: list[dict] = field(default_factory=list)  # Conflicting claims
    ranked_results: list = field(default_factory=list)  # All search results (RankedResult)
    query: str = ""                       # Original query
    query_type: str = ""                  # Classified query type


# ---------------------------------------------------------------------------
# MemoryRetrieval — the orchestrator
# ---------------------------------------------------------------------------


class MemoryRetrieval:
    """Orchestrates the full memory retrieval pipeline:

    QueryUnderstanding -> search -> [Reranker] -> assemble response

    This is the orchestrator. It delegates to:
    - QueryUnderstanding for query classification
    - Existing searcher for vector/keyword/graph search
    - Reranker for post-retrieval ranking
    - ProvenanceTracker for provenance chains
    - ConflictDetector for conflicting claims
    - DecisionRecorder for decision context

    It does NOT reimplement any of their logic.
    """

    def __init__(
        self,
        searcher=None,
        reranker=None,
        provenance_tracker=None,
        conflict_detector=None,
        decision_recorder=None,
    ):
        self.query_understanding = QueryUnderstanding()
        self.searcher = searcher
        self.reranker = reranker or Reranker()
        self.provenance = provenance_tracker
        self.conflicts = conflict_detector
        self.decisions = decision_recorder

    # ------------------------------------------------------------------
    # retrieve
    # ------------------------------------------------------------------

    def retrieve(self, query: str) -> MemoryResponse:
        """Full retrieval pipeline.

        1. QueryUnderstanding.understand(query) -> UnderstoodQuery
        2. Route search based on query type + target memory types
        3. Reranker.rerank(results, query) -> ranked results
        4. For top result: fetch provenance, related decisions, conflicts
        5. Assemble MemoryResponse
        """
        understood = self.query_understanding.understand(query)

        # 2. Search with inferred memory types
        results = self._search_by_memory_types(query, understood.target_memory_types)

        # 3. Convert + rerank
        ranked = self._rerank_results(results, query)

        # 4-5. Enrich top result + assemble
        top = ranked[0] if ranked else None
        return self._assemble_response(query, understood, ranked, top)

    # ------------------------------------------------------------------
    # recall
    # ------------------------------------------------------------------

    def recall(self, object_id: str) -> MemoryResponse:
        """Direct recall of a specific object by ID.

        1. Load the object
        2. Get provenance chain
        3. Get related decisions
        4. Return assembled response
        """
        mem_obj = None

        # 1. Try to load the object via searcher
        if self.searcher is not None:
            try:
                raw_results = self.searcher(object_id, memory_types=[])
                if raw_results:
                    first = raw_results[0]
                    if isinstance(first, dict):
                        mem_obj = dict(first)
                    elif isinstance(first, RankedResult):
                        mem_obj = self._result_to_memory_object(first)
            except Exception:
                pass

        # 2. Get provenance chain
        provenance = None
        if self.provenance is not None:
            try:
                chain = self.provenance.get_provenance_chain(object_id)
                if chain:
                    provenance = chain
            except Exception:
                pass

        # 3. Get related decisions
        decisions: list[dict] = []
        if self.decisions is not None:
            try:
                ctx = self.decisions.get_decision_context(object_id)
                if ctx:
                    decisions = [ctx]
            except Exception:
                pass

        # Assemble ranked_results list for consistency
        ranked: list = []
        if mem_obj is not None:
            ranked = [
                RankedResult(
                    object_id=object_id,
                    title=mem_obj.get("title", ""),
                    content=mem_obj.get("content", ""),
                    score=1.0,
                    source="recall",
                    metadata=mem_obj.get("metadata", {}),
                )
            ]

        return MemoryResponse(
            memory_object=mem_obj,
            provenance_chain=provenance,
            related_decisions=decisions,
            conflicting_claims=[],
            ranked_results=ranked,
            query=object_id,
            query_type="recall",
        )

    # ------------------------------------------------------------------
    # _search_by_memory_types
    # ------------------------------------------------------------------

    def _search_by_memory_types(self, query: str, memory_types: list[str]) -> list:
        """Route search to appropriate backends based on memory types.

        If searcher is available, use it. Otherwise return empty results
        (degraded mode).
        """
        if self.searcher is None:
            return []
        try:
            return self.searcher(query, memory_types=memory_types) or []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # _rerank_results
    # ------------------------------------------------------------------

    def _rerank_results(self, results: list, query: str) -> list:
        """Convert search results to RankedResult and pass through Reranker."""
        if not results:
            return []

        # Convert mixed formats to RankedResult
        ranked: list[RankedResult] = []
        for r in results:
            if isinstance(r, RankedResult):
                ranked.append(r)
            elif isinstance(r, dict):
                ranked.append(
                    RankedResult(
                        object_id=r.get("path", r.get("object_id", "")),
                        title=r.get("title", ""),
                        content=r.get("content", r.get("snippet", "")),
                        score=float(r.get("score", 0.0)),
                        source=r.get("source", "search"),
                        metadata=r.get("metadata", {}),
                    )
                )

        if not ranked:
            return []

        return self.reranker.rerank(ranked, query)

    # ------------------------------------------------------------------
    # _assemble_response
    # ------------------------------------------------------------------

    def _assemble_response(
        self,
        query: str,
        understood_query: UnderstoodQuery,
        results: list,
        top_object: RankedResult | None = None,
    ) -> MemoryResponse:
        """Assemble the final MemoryResponse from search results + enrichments."""
        mem_obj = None
        provenance = None
        decisions: list[dict] = []
        conflicts: list[dict] = []

        if top_object is not None:
            mem_obj = self._result_to_memory_object(top_object)
            obj_id = top_object.object_id

            # Enrich: provenance
            if obj_id and self.provenance is not None:
                try:
                    chain = self.provenance.get_provenance_chain(obj_id)
                    if chain:
                        provenance = chain
                except Exception:
                    pass

            # Enrich: related decisions
            if obj_id and self.decisions is not None:
                try:
                    ctx = self.decisions.get_decision_context(obj_id)
                    if ctx:
                        decisions = [ctx]
                except Exception:
                    pass

            # Enrich: conflicting claims — requires Claim objects which are
            # not directly available from search results.  Populated when the
            # caller has claims to feed to ConflictDetector.
            if obj_id and self.conflicts is not None:
                try:
                    # ConflictDetector.detect() needs a list of Claim objects.
                    # Without claims from the search pipeline we pass an empty
                    # list — this is a hook point for future enrichment.
                    pass
                except Exception:
                    pass

        return MemoryResponse(
            memory_object=mem_obj,
            provenance_chain=provenance,
            related_decisions=decisions,
            conflicting_claims=conflicts,
            ranked_results=results,
            query=query,
            query_type=understood_query.type.value,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _result_to_memory_object(result: RankedResult | dict) -> dict:
        """Convert a RankedResult or dict to the memory_object dict."""
        if isinstance(result, RankedResult):
            return {
                "object_id": result.object_id,
                "title": result.title,
                "content": result.content,
                "score": result.score,
                "source": result.source,
            }
        return dict(result)
