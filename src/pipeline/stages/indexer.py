"""IndexerStage — terminal pipeline stage for vectors + graph + lifecycle.

Runs after commit_ingest writes WikiPage files. Handles:
  (a) Vector embedding upsert — reuses existing vector infrastructure
  (b) Append knowledge graph nodes/edges
  (c) Transition KnowledgeObject lifecycle to ACTIVE
  (d) Increment ingest counter; trigger snapshot rebuild every 100 ingests
"""
from __future__ import annotations

import logging
from datetime import datetime

from src.knowledge.core.adapter import wiki_page_to_knowledge_object
from src.knowledge.core.object import KnowledgeObject, LifecycleState
from src.knowledge.core.lifecycle import LifecycleEngine
from src.knowledge.graph.builder import (
    GraphBuilder,
    GraphNode,
    GraphEdge,
    NodeType,
    EdgeType,
)
from src.llm.embedding_runtime import get_embedding_provider
from src.types import VectorChunk
from src.utils.path import normalize_source_path
from src.utils.text import chunk_markdown
from src.vector.upsert import vector_upsert_chunks
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import WikiPage

_logger = logging.getLogger(__name__)

# KnowledgeType value → NodeType mapping (same semantics as graph builder)
_KNOWLEDGE_TYPE_TO_NODE_TYPE: dict[str, NodeType] = {
    "document": NodeType.DOCUMENT,
    "entity": NodeType.ENTITY,
    "concept": NodeType.CONCEPT,
    "claim": NodeType.CLAIM,
    "decision": NodeType.DECISION,
    "event": NodeType.EVENT,
    "procedure": NodeType.CONCEPT,
    "synthesis": NodeType.CONCEPT,
}


class IndexerStage:
    """Terminal pipeline stage. Runs after commit_ingest.

    Responsibilities:
      (a) Vector embedding upsert — reuse existing vector infrastructure
      (b) Append knowledge graph events to events.jsonl
      (c) Transition KnowledgeObject lifecycle to ACTIVE
      (d) Increment ingest counter; trigger graph snapshot rebuild every 100 ingests

    This is a SEPARATE stage from commit_ingest. commit_ingest handles
    atomic WikiPage file writes + index.md + log.md. Indexer handles
    vectors + graph + lifecycle transitions.

    Usage::

        indexer = IndexerStage()
        await indexer.index(wiki_page, paths, graph_builder, lifecycle_engine)
    """

    # Class-level counter shared across all instances
    _ingest_count_since_snapshot: int = 0
    SNAPSHOT_INTERVAL: int = 100

    async def index(
        self,
        wiki_page: WikiPage,
        paths: WikiPaths,
        graph_builder: GraphBuilder,
        lifecycle_engine: LifecycleEngine,
    ) -> None:
        """Run full indexing pipeline for a single wiki page.

        1. Convert WikiPage → KnowledgeObject via adapter
        2. Upsert vector embedding (failure does not block graph/lifecycle)
        3. Add nodes + edges to graph
        4. Transition lifecycle to ACTIVE
        5. Increment counter; if >= SNAPSHOT_INTERVAL, trigger graph snapshot rebuild
        """
        ko = wiki_page_to_knowledge_object(wiki_page)

        # 2. Vector embedding upsert — failure is logged but does not block
        try:
            await self._upsert_vectors(ko, paths)
        except Exception:
            _logger.error(
                "Indexer: vector upsert failed for %s",
                ko.id, exc_info=True,
            )

        # 3. Add to knowledge graph
        self._add_to_graph(ko, graph_builder)

        # 4. Transition lifecycle to ACTIVE
        reason = "indexer:index_complete"
        self._transition_to_active(ko, lifecycle_engine, reason)

        # 5. Increment counter; trigger snapshot if threshold reached
        self._increment_and_check_snapshot(graph_builder)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _upsert_vectors(self, ko: KnowledgeObject, paths: WikiPaths) -> None:
        """Chunk content, request embeddings, and upsert to the vector store."""
        content = ko.content or ko.title or ""
        if not content.strip():
            _logger.debug("Indexer: empty content for %s, skipping vector upsert", ko.id)
            return

        chunks = chunk_markdown(content)
        provider = get_embedding_provider()

        # Get embeddings — handle both concrete provider objects (with .embedding
        # attribute) and protocol-style plain lists
        embedding_results = await provider.embed(chunks)
        if embedding_results and hasattr(embedding_results[0], "embedding"):
            embeddings = [e.embedding for e in embedding_results]
        else:
            embeddings = list(embedding_results)

        if not embeddings or len(embeddings) != len(chunks):
            _logger.warning(
                "Indexer: embedding mismatch for %s (%d chunks, %d embeddings)",
                ko.id, len(chunks), len(embeddings),
            )
            return

        from datetime import timezone
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        lance_chunks = [
            VectorChunk(
                id=f"{ko.id}-chunk-{i}",
                task_id=ko.id,
                content=chunk,
                embedding=embeddings[i],
                path=normalize_source_path(ko.id, paths.root),
                updated_at=now,
            )
            for i, chunk in enumerate(chunks)
        ]
        vector_upsert_chunks(lance_chunks)
        _logger.debug("Indexer: upserted %d vector chunks for %s", len(lance_chunks), ko.id)

    def _add_to_graph(self, ko: KnowledgeObject, graph_builder: GraphBuilder) -> None:
        """Add a node for *ko* plus edges for relations and provenance."""
        # Resolve KnowledgeType → NodeType
        ko_type_str = ko.type.value if hasattr(ko.type, "value") else str(ko.type)
        node_type = _KNOWLEDGE_TYPE_TO_NODE_TYPE.get(ko_type_str, NodeType.CONCEPT)

        # Node
        graph_builder.add_node(GraphNode(
            id=ko.id,
            type=node_type,
            label=ko.title,
            properties={"confidence": ko.confidence, "grade": ko.grade},
        ))

        # Edges from relations
        for rel in (ko.relations or []):
            if isinstance(rel, dict):
                target_id = rel.get("target_id", "")
                rel_type = rel.get("type", "relates_to")
            else:
                target_id = getattr(rel, "target_id", "")
                rel_type = getattr(rel, "type", "relates_to")
            if target_id:
                edge_id = f"{ko.id}--relates_to--{target_id}"
                graph_builder.add_edge(GraphEdge(
                    id=edge_id,
                    type=EdgeType.RELATES_TO,
                    source_id=ko.id,
                    target_id=target_id,
                    properties={"relation_type": str(rel_type)},
                ))

        # DERIVES_FROM edge from provenance source_path
        provenance = getattr(ko, "provenance", None)
        if provenance is not None:
            source_path = getattr(provenance, "source_path", "")
            if source_path:
                doc_id = f"doc--{source_path}"
                if graph_builder.get_node(doc_id) is None:
                    graph_builder.add_node(GraphNode(
                        id=doc_id,
                        type=NodeType.DOCUMENT,
                        label=source_path,
                    ))
                edge_id = f"{ko.id}--derives_from--{doc_id}"
                graph_builder.add_edge(GraphEdge(
                    id=edge_id,
                    type=EdgeType.DERIVES_FROM,
                    source_id=doc_id,
                    target_id=ko.id,
                ))

    @staticmethod
    def _transition_to_active(
        ko: KnowledgeObject,
        lifecycle_engine: LifecycleEngine,
        reason: str,
    ) -> None:
        """Transition *ko* lifecycle to ACTIVE.

        Because PROCESSING → ACTIVE is not a direct edge in the lifecycle
        state machine, we route through REVIEWING when needed::

            PROCESSING → REVIEWING → ACTIVE
            REVIEWING  → ACTIVE
            ACTIVE     → no-op
        """
        try:
            if ko.lifecycle == LifecycleState.CREATED:
                lifecycle_engine.transition(ko, LifecycleState.PROCESSING, reason)
                lifecycle_engine.transition(ko, LifecycleState.REVIEWING, reason)
                lifecycle_engine.transition(ko, LifecycleState.ACTIVE, reason)
            elif ko.lifecycle == LifecycleState.PROCESSING:
                lifecycle_engine.transition(ko, LifecycleState.REVIEWING, reason)
                lifecycle_engine.transition(ko, LifecycleState.ACTIVE, reason)
            elif ko.lifecycle == LifecycleState.REVIEWING:
                lifecycle_engine.transition(ko, LifecycleState.ACTIVE, reason)
            elif ko.lifecycle == LifecycleState.ACTIVE:
                _logger.debug("Indexer: %s is already ACTIVE, skipping transition", ko.id)
            else:
                lifecycle_engine.transition(ko, LifecycleState.ACTIVE, reason)
        except ValueError:
            _logger.warning(
                "Indexer: cannot transition %s from %s to ACTIVE",
                ko.id, ko.lifecycle.value, exc_info=True,
            )

    @classmethod
    def _increment_and_check_snapshot(cls, graph_builder: GraphBuilder) -> None:
        """Increment counter; rebuild graph snapshot every SNAPSHOT_INTERVAL ingests."""
        cls._ingest_count_since_snapshot += 1
        if cls._ingest_count_since_snapshot >= cls.SNAPSHOT_INTERVAL:
            graph_builder.rebuild_snapshot()
            _logger.info(
                "Indexer: snapshot rebuilt after %d ingests",
                cls.SNAPSHOT_INTERVAL,
            )
            cls._ingest_count_since_snapshot = 0
