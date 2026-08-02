"""In-memory knowledge graph with append-only JSONL event log + periodic snapshot.

Storage:
    {wiki_paths.index}/knowledge_graph/events.jsonl  — append-only event log
    {wiki_paths.index}/knowledge_graph/snapshot.json  — full snapshot (rebuilt every 100 events)
"""

from dataclasses import dataclass, field
from enum import Enum
import json
import time

from src.lib.write_hooks import safe_write
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class NodeType(str, Enum):
    ENTITY = "entity"
    CONCEPT = "concept"
    CLAIM = "claim"
    DECISION = "decision"
    DOCUMENT = "document"
    EVENT = "event"


class EdgeType(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVES_FROM = "derives_from"
    RELATES_TO = "relates_to"
    PRECEDES = "precedes"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    id: str
    type: NodeType
    label: str
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GraphNode":
        return cls(
            id=d["id"],
            type=NodeType(d["type"]),
            label=d["label"],
            properties=d.get("properties", {}),
        )


@dataclass
class GraphEdge:
    """A directed edge between two nodes in the knowledge graph."""

    id: str
    type: EdgeType
    source_id: str
    target_id: str
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GraphEdge":
        return cls(
            id=d["id"],
            type=EdgeType(d["type"]),
            source_id=d["source_id"],
            target_id=d["target_id"],
            properties=d.get("properties", {}),
        )


# ---------------------------------------------------------------------------
# KnowledgeType → NodeType mapping (used by build_from_objects)
# ---------------------------------------------------------------------------

_KNOWLEDGE_TYPE_TO_NODE_TYPE: dict[str, NodeType] = {
    "document": NodeType.DOCUMENT,
    "entity": NodeType.ENTITY,
    "concept": NodeType.CONCEPT,
    "claim": NodeType.CLAIM,
    "decision": NodeType.DECISION,
    "event": NodeType.EVENT,
    # No direct NodeType for these — map to CONCEPT
    "procedure": NodeType.CONCEPT,
    "synthesis": NodeType.CONCEPT,
}


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------


class GraphBuilder:
    """In-memory knowledge graph with append-only JSONL + periodic snapshot.

    All mutations are recorded to an append-only events log (events.jsonl).
    Every SNAPSHOT_THRESHOLD events, a full snapshot (snapshot.json) is
    rebuilt so that startup load time stays bounded.

    On init, the builder loads the snapshot (if any) and replays events
    appended since the snapshot was last rebuilt.
    """

    SNAPSHOT_THRESHOLD = 100

    def __init__(self, wiki_paths: WikiPaths) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._event_count_since_snapshot: int = 0
        self._total_events: int = 0
        self._events_path = wiki_paths.index / "knowledge_graph" / "events.jsonl"
        self._snapshot_path = wiki_paths.index / "knowledge_graph" / "snapshot.json"
        self._ensure_dirs()
        self._load_snapshot()
        self._replay_events()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        """Add or update a node. Emits upsert_node event."""
        self._nodes[node.id] = node
        event = {
            "action": "upsert_node",
            "node": node.to_dict(),
            "timestamp": int(time.time() * 1000),
        }
        self._append_event(event)

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all edges connected to it. Emits delete_node events."""
        if node_id not in self._nodes:
            return
        del self._nodes[node_id]
        # Cascade: remove all edges connected to this node
        edges_to_remove = [
            eid for eid, edge in self._edges.items()
            if edge.source_id == node_id or edge.target_id == node_id
        ]
        for eid in edges_to_remove:
            del self._edges[eid]
        # Emit delete_node event (edge deletions are implicit via cascade)
        event = {
            "action": "delete_node",
            "node_id": node_id,
            "timestamp": int(time.time() * 1000),
        }
        self._append_event(event)

    def get_node(self, node_id: str) -> GraphNode | None:
        """Return the node with *node_id*, or None."""
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, node_type: NodeType) -> list[GraphNode]:
        """Return all nodes of *node_type*."""
        return [n for n in self._nodes.values() if n.type == node_type]

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> None:
        """Add or update an edge. Emits upsert_edge event."""
        self._edges[edge.id] = edge
        event = {
            "action": "upsert_edge",
            "edge": edge.to_dict(),
            "timestamp": int(time.time() * 1000),
        }
        self._append_event(event)

    def remove_edge(self, edge_id: str) -> None:
        """Remove an edge. Emits delete_edge event."""
        if edge_id not in self._edges:
            return
        del self._edges[edge_id]
        event = {
            "action": "delete_edge",
            "edge_id": edge_id,
            "timestamp": int(time.time() * 1000),
        }
        self._append_event(event)

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        """Return the edge with *edge_id*, or None."""
        return self._edges.get(edge_id)

    def get_edges_for_node(self, node_id: str) -> list[GraphEdge]:
        """All edges where *node_id* is source or target."""
        return [
            e for e in self._edges.values()
            if e.source_id == node_id or e.target_id == node_id
        ]

    def get_neighbors(self, node_id: str) -> list[tuple[GraphNode, GraphEdge]]:
        """Return (neighbor_node, connecting_edge) for all connected nodes."""
        results: list[tuple[GraphNode, GraphEdge]] = []
        for edge in self._edges.values():
            if edge.source_id == node_id:
                neighbor = self._nodes.get(edge.target_id)
                if neighbor is not None:
                    results.append((neighbor, edge))
            elif edge.target_id == node_id:
                neighbor = self._nodes.get(edge.source_id)
                if neighbor is not None:
                    results.append((neighbor, edge))
        return results

    # ------------------------------------------------------------------
    # Graph construction helpers
    # ------------------------------------------------------------------

    def build_from_objects(self, objects: list) -> None:
        """Build graph nodes+edges from a list of KnowledgeObjects.

        For each object:
        - Create a node (type mapped from KnowledgeType)
        - For each relation in object.relations, create a RELATES_TO edge
        - From provenance, create a DERIVES_FROM edge to the source document
        """
        for obj in objects:
            node_type = _KNOWLEDGE_TYPE_TO_NODE_TYPE.get(
                obj.type.value if hasattr(obj.type, "value") else str(obj.type),
                NodeType.CONCEPT,
            )
            self.add_node(GraphNode(
                id=obj.id,
                type=node_type,
                label=obj.title,
                properties={"confidence": obj.confidence, "grade": obj.grade},
            ))

            # Relations: each entry is a dict with at least target_id
            for rel in (obj.relations or []):
                if isinstance(rel, dict):
                    target_id = rel.get("target_id", "")
                    rel_type = rel.get("type", "relates_to")
                else:
                    target_id = getattr(rel, "target_id", "")
                    rel_type = getattr(rel, "type", "relates_to")
                if target_id:
                    edge_id = f"{obj.id}--relates_to--{target_id}"
                    self.add_edge(GraphEdge(
                        id=edge_id,
                        type=EdgeType.RELATES_TO,
                        source_id=obj.id,
                        target_id=target_id,
                        properties={"relation_type": str(rel_type)},
                    ))

            # Provenance: DERIVES_FROM edge to source document
            provenance = getattr(obj, "provenance", None)
            if provenance is not None:
                source_path = getattr(provenance, "source_path", "")
                if source_path:
                    doc_id = f"doc--{source_path}"
                    # Ensure the document node exists
                    if doc_id not in self._nodes:
                        self.add_node(GraphNode(
                            id=doc_id,
                            type=NodeType.DOCUMENT,
                            label=source_path,
                        ))
                    edge_id = f"{obj.id}--derives_from--{doc_id}"
                    self.add_edge(GraphEdge(
                        id=edge_id,
                        type=EdgeType.DERIVES_FROM,
                        source_id=doc_id,
                        target_id=obj.id,
                    ))

    def add_claim_with_evidence(self, claim, knowledge_object_id: str) -> None:
        """Add a Claim node + DERIVES_FROM edges to its source objects.

        The *claim* should be a Claim dataclass (src.knowledge.claims.model.Claim).
        A corresponding node is created from the claim data, and DERIVES_FROM
        edges connect the claim node to each knowledge object listed in
        claim.source_objects.
        """
        claim_node_id = claim.id
        self.add_node(GraphNode(
            id=claim_node_id,
            type=NodeType.CLAIM,
            label=claim.statement[:120],
            properties={
                "confidence": claim.confidence,
                "status": claim.status.value,
                "claim_type": claim.type.value,
            },
        ))

        # DERIVES_FROM from each source object to the claim
        for idx, source_obj_id in enumerate(claim.source_objects or []):
            edge_id = f"{claim_node_id}--derives_from--{source_obj_id}--{idx}"
            self.add_edge(GraphEdge(
                id=edge_id,
                type=EdgeType.DERIVES_FROM,
                source_id=source_obj_id,
                target_id=claim_node_id,
            ))

        # Also add evidence-based SUPPORTS edges
        for idx, evidence in enumerate(claim.evidence or []):
            evidence_node_id = f"{claim_node_id}--evidence--{idx}"
            self.add_node(GraphNode(
                id=evidence_node_id,
                type=NodeType.DOCUMENT,
                label=f"Evidence: {evidence.source_path}",
                properties={
                    "source_path": evidence.source_path,
                    "page": evidence.page,
                    "quote": evidence.quote,
                },
            ))
            edge_id = f"{evidence_node_id}--supports--{claim_node_id}"
            self.add_edge(GraphEdge(
                id=edge_id,
                type=EdgeType.SUPPORTS,
                source_id=evidence_node_id,
                target_id=claim_node_id,
            ))

    def add_conflict_edge(self, claim_a_id: str, claim_b_id: str) -> None:
        """Add a CONTRADICTS edge between two conflicting claims."""
        edge_id = f"{claim_a_id}--contradicts--{claim_b_id}"
        self.add_edge(GraphEdge(
            id=edge_id,
            type=EdgeType.CONTRADICTS,
            source_id=claim_a_id,
            target_id=claim_b_id,
        ))

    # ------------------------------------------------------------------
    # Public query
    # ------------------------------------------------------------------

    def query(self) -> dict:
        """Return current graph state as {nodes: [...], edges: [...]}."""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
        }

    # ------------------------------------------------------------------
    # Snapshot management (public)
    # ------------------------------------------------------------------

    def rebuild_snapshot(self) -> None:
        """Rebuild snapshot.json from current in-memory state. Reset event counter."""
        data = {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
            "total_events": self._total_events,
        }
        safe_write(self._snapshot_path, json.dumps(data, ensure_ascii=False, indent=2))
        self._event_count_since_snapshot = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Create the knowledge_graph directory if it does not exist."""
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_snapshot(self) -> None:
        """Load nodes + edges from snapshot.json if it exists."""
        try:
            raw = self._snapshot_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return

        data = json.loads(raw)
        self._nodes.clear()
        self._edges.clear()

        for node_dict in data.get("nodes", []):
            node = GraphNode.from_dict(node_dict)
            self._nodes[node.id] = node

        for edge_dict in data.get("edges", []):
            edge = GraphEdge.from_dict(edge_dict)
            self._edges[edge.id] = edge

        # Capture the event count at snapshot time
        self._total_events = data.get("total_events", 0)
        self._event_count_since_snapshot = 0

    def _replay_events(self) -> None:
        """Replay events.jsonl entries newer than the last snapshot.

        Only processes events beyond the snapshot's recorded event count.
        Uses line-number-based skipping: line N corresponds to event N.
        """
        try:
            with open(self._events_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (FileNotFoundError, OSError):
            return

        # Snapshot's event count at the time it was built
        snapshot_event_count = self._total_events

        # Skip lines already included in the snapshot.
        # Events are numbered from 1; replay only those after snapshot_event_count.
        for idx, line in enumerate(lines, start=1):
            if idx <= snapshot_event_count:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            self._apply_event(event)
            self._total_events = idx
        self._event_count_since_snapshot = self._total_events - snapshot_event_count

    def _append_event(self, event: dict) -> None:
        """Append a single event line to events.jsonl. Uses atomic append."""
        self._total_events += 1
        self._event_count_since_snapshot += 1
        event["event_index"] = self._total_events

        line = json.dumps(event, ensure_ascii=False) + "\n"
        # Append-only: no lock needed for single-writer scenarios
        with open(self._events_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()

        # Auto-trigger snapshot rebuild after threshold
        if self._event_count_since_snapshot >= self.SNAPSHOT_THRESHOLD:
            self.rebuild_snapshot()

    def _apply_event(self, event: dict) -> None:
        """Apply a single parsed event to in-memory state."""
        action = event.get("action")
        if action == "upsert_node":
            node_dict = event.get("node")
            if node_dict:
                node = GraphNode.from_dict(node_dict)
                self._nodes[node.id] = node
        elif action == "delete_node":
            node_id = event.get("node_id")
            if node_id:
                self._nodes.pop(node_id, None)
                # Cascade: remove connected edges
                edges_to_remove = [
                    eid for eid, edge in self._edges.items()
                    if edge.source_id == node_id or edge.target_id == node_id
                ]
                for eid in edges_to_remove:
                    del self._edges[eid]
        elif action == "upsert_edge":
            edge_dict = event.get("edge")
            if edge_dict:
                edge = GraphEdge.from_dict(edge_dict)
                self._edges[edge.id] = edge
        elif action == "delete_edge":
            edge_id = event.get("edge_id")
            if edge_id:
                self._edges.pop(edge_id, None)
