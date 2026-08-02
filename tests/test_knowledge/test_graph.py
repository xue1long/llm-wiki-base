"""Test GraphBuilder — append-only JSONL + snapshot knowledge graph (Task 2.6)."""
import json
import pytest

from src.knowledge.graph.builder import (
    EdgeType,
    GraphBuilder,
    GraphEdge,
    GraphNode,
    NodeType,
)
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wiki_paths(tmp_path):
    """Return WikiPaths rooted in a temporary directory."""
    return WikiPaths(root=tmp_path)


@pytest.fixture
def builder(wiki_paths):
    """Return a fresh GraphBuilder backed by tmp_path."""
    gb = GraphBuilder(wiki_paths)
    yield gb
    # Clean up the graph directory to isolate tests
    import shutil
    graph_dir = wiki_paths.index / "knowledge_graph"
    if graph_dir.exists():
        shutil.rmtree(graph_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(nid="n1", ntype=NodeType.ENTITY, label="Test Node", props=None):
    return GraphNode(id=nid, type=ntype, label=label, properties=props or {})


def _make_edge(eid="e1", etype=EdgeType.RELATES_TO, src="n1", tgt="n2", props=None):
    return GraphEdge(id=eid, type=etype, source_id=src, target_id=tgt, properties=props or {})


# ---------------------------------------------------------------------------
# 1. add_node + get_node
# ---------------------------------------------------------------------------


class TestAddNode:
    def test_add_and_retrieve(self, builder):
        node = _make_node("entity-1", NodeType.ENTITY, "Alice")
        builder.add_node(node)
        retrieved = builder.get_node("entity-1")
        assert retrieved is not None
        assert retrieved.id == "entity-1"
        assert retrieved.type == NodeType.ENTITY
        assert retrieved.label == "Alice"

    def test_add_twice_updates(self, builder):
        builder.add_node(_make_node("n1", NodeType.ENTITY, "First"))
        builder.add_node(_make_node("n1", NodeType.CONCEPT, "Second"))
        n = builder.get_node("n1")
        assert n.label == "Second"
        assert n.type == NodeType.CONCEPT


# ---------------------------------------------------------------------------
# 2. add_edge + get_edge
# ---------------------------------------------------------------------------


class TestAddEdge:
    def test_add_and_retrieve(self, builder):
        builder.add_node(_make_node("a"))
        builder.add_node(_make_node("b"))
        edge = _make_edge("e1", EdgeType.RELATES_TO, "a", "b")
        builder.add_edge(edge)
        retrieved = builder.get_edge("e1")
        assert retrieved is not None
        assert retrieved.id == "e1"
        assert retrieved.type == EdgeType.RELATES_TO
        assert retrieved.source_id == "a"
        assert retrieved.target_id == "b"

    def test_add_twice_updates(self, builder):
        builder.add_node(_make_node("a"))
        builder.add_node(_make_node("b"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "a", "b"))
        builder.add_edge(_make_edge("e1", EdgeType.SUPPORTS, "a", "b"))
        e = builder.get_edge("e1")
        assert e.type == EdgeType.SUPPORTS

    def test_edge_missing_returns_none(self, builder):
        assert builder.get_edge("nonexistent") is None


# ---------------------------------------------------------------------------
# 3. remove_node
# ---------------------------------------------------------------------------


class TestRemoveNode:
    def test_remove_existing(self, builder):
        builder.add_node(_make_node("n1"))
        assert builder.get_node("n1") is not None
        builder.remove_node("n1")
        assert builder.get_node("n1") is None

    def test_remove_nonexistent_no_error(self, builder):
        builder.remove_node("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# 4. remove_edge
# ---------------------------------------------------------------------------


class TestRemoveEdge:
    def test_remove_existing(self, builder):
        builder.add_node(_make_node("a"))
        builder.add_node(_make_node("b"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "a", "b"))
        assert builder.get_edge("e1") is not None
        builder.remove_edge("e1")
        assert builder.get_edge("e1") is None

    def test_remove_nonexistent_no_error(self, builder):
        builder.remove_edge("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# 5. Cascade edge removal on node delete
# ---------------------------------------------------------------------------


class TestCascadeEdgeRemoval:
    def test_deleting_node_removes_connected_edges(self, builder):
        builder.add_node(_make_node("a"))
        builder.add_node(_make_node("b"))
        builder.add_node(_make_node("c"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "a", "b"))
        builder.add_edge(_make_edge("e2", EdgeType.SUPPORTS, "c", "a"))
        builder.add_edge(_make_edge("e3", EdgeType.RELATES_TO, "b", "c"))

        builder.remove_node("a")

        # Node a gone
        assert builder.get_node("a") is None
        # Edges connected to a gone
        assert builder.get_edge("e1") is None
        assert builder.get_edge("e2") is None
        # Edge not involving a survives
        assert builder.get_edge("e3") is not None


# ---------------------------------------------------------------------------
# 6. get_nodes_by_type
# ---------------------------------------------------------------------------


class TestGetNodesByType:
    def test_filter_by_type(self, builder):
        builder.add_node(_make_node("e1", NodeType.ENTITY, "Ent1"))
        builder.add_node(_make_node("e2", NodeType.ENTITY, "Ent2"))
        builder.add_node(_make_node("c1", NodeType.CONCEPT, "Con1"))
        builder.add_node(_make_node("cl1", NodeType.CLAIM, "Claim1"))

        entities = builder.get_nodes_by_type(NodeType.ENTITY)
        concepts = builder.get_nodes_by_type(NodeType.CONCEPT)
        claims = builder.get_nodes_by_type(NodeType.CLAIM)

        assert len(entities) == 2
        assert len(concepts) == 1
        assert len(claims) == 1
        assert {n.id for n in entities} == {"e1", "e2"}

    def test_empty_result(self, builder):
        assert builder.get_nodes_by_type(NodeType.DOCUMENT) == []


# ---------------------------------------------------------------------------
# 7. get_edges_for_node
# ---------------------------------------------------------------------------


class TestGetEdgesForNode:
    def test_returns_all_connected_edges(self, builder):
        builder.add_node(_make_node("a"))
        builder.add_node(_make_node("b"))
        builder.add_node(_make_node("c"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "a", "b"))
        builder.add_edge(_make_edge("e2", EdgeType.SUPPORTS, "c", "a"))
        builder.add_edge(_make_edge("e3", EdgeType.RELATES_TO, "b", "c"))

        edges_for_a = builder.get_edges_for_node("a")
        assert len(edges_for_a) == 2
        assert {e.id for e in edges_for_a} == {"e1", "e2"}

    def test_node_with_no_edges(self, builder):
        builder.add_node(_make_node("lonely"))
        assert builder.get_edges_for_node("lonely") == []


# ---------------------------------------------------------------------------
# 8. get_neighbors
# ---------------------------------------------------------------------------


class TestGetNeighbors:
    def test_returns_neighbor_edge_tuples(self, builder):
        builder.add_node(_make_node("a", label="Node A"))
        builder.add_node(_make_node("b", label="Node B"))
        builder.add_node(_make_node("c", label="Node C"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "a", "b"))
        builder.add_edge(_make_edge("e2", EdgeType.SUPPORTS, "c", "a"))

        neighbors = builder.get_neighbors("a")
        assert len(neighbors) == 2

        neighbor_ids = {n[0].id for n in neighbors}
        edge_ids = {n[1].id for n in neighbors}
        assert neighbor_ids == {"b", "c"}
        assert edge_ids == {"e1", "e2"}

    def test_empty_for_isolated_node(self, builder):
        builder.add_node(_make_node("lonely"))
        assert builder.get_neighbors("lonely") == []


# ---------------------------------------------------------------------------
# 9. build_from_objects — relations
# ---------------------------------------------------------------------------


class TestBuildFromObjects:
    def test_creates_nodes_and_relates_to_edges(self, builder):
        """Feed KnowledgeObjects with relations → correct nodes + RELATES_TO edges."""
        from src.knowledge.core.object import (
            KnowledgeObject,
            KnowledgeType,
            LifecycleState,
            Provenance,
        )

        obj_a = KnowledgeObject(
            id="ko-a", type=KnowledgeType.ENTITY, title="Entity A",
            content="x", lifecycle=LifecycleState.ACTIVE, confidence=0.9,
            provenance=Provenance(source_path="/src/test.md"),
            relations=[{"target_id": "ko-b", "type": "references"}],
        )
        obj_b = KnowledgeObject(
            id="ko-b", type=KnowledgeType.CONCEPT, title="Concept B",
            content="y", lifecycle=LifecycleState.ACTIVE, confidence=0.7,
            provenance=Provenance(source_path="/src/test.md"),
            relations=[],
        )

        builder.build_from_objects([obj_a, obj_b])

        # Nodes exist
        assert builder.get_node("ko-a") is not None
        assert builder.get_node("ko-b") is not None
        assert builder.get_node("ko-a").type == NodeType.ENTITY
        assert builder.get_node("ko-b").type == NodeType.CONCEPT

        # RELATES_TO edge from ko-a to ko-b
        edges = builder.get_edges_for_node("ko-a")
        relates_edges = [e for e in edges if e.type == EdgeType.RELATES_TO]
        assert len(relates_edges) == 1
        assert relates_edges[0].source_id == "ko-a"
        assert relates_edges[0].target_id == "ko-b"

    def test_maps_procedure_and_synthesis_to_concept(self, builder):
        """KnowledgeType without a direct NodeType (procedure, synthesis) → CONCEPT."""
        from src.knowledge.core.object import (
            KnowledgeObject,
            KnowledgeType,
            LifecycleState,
            Provenance,
        )

        obj = KnowledgeObject(
            id="ko-proc", type=KnowledgeType.PROCEDURE, title="A Procedure",
            content="steps", lifecycle=LifecycleState.ACTIVE, confidence=0.5,
            provenance=Provenance(source_path="/src/p.md"),
            relations=[],
        )
        builder.build_from_objects([obj])
        node = builder.get_node("ko-proc")
        assert node is not None
        assert node.type == NodeType.CONCEPT


# ---------------------------------------------------------------------------
# 10. build_from_objects — provenance → DERIVES_FROM
# ---------------------------------------------------------------------------


class TestBuildFromObjectsProvenance:
    def test_creates_derives_from_edge(self, builder):
        from src.knowledge.core.object import (
            KnowledgeObject,
            KnowledgeType,
            LifecycleState,
            Provenance,
        )

        obj = KnowledgeObject(
            id="ko-x", type=KnowledgeType.ENTITY, title="Entity X",
            content="z", lifecycle=LifecycleState.ACTIVE, confidence=0.8,
            provenance=Provenance(source_path="/docs/source.pdf"),
            relations=[],
        )
        builder.build_from_objects([obj])

        doc_id = "doc--/docs/source.pdf"
        # Document node created
        assert builder.get_node(doc_id) is not None
        assert builder.get_node(doc_id).type == NodeType.DOCUMENT

        # DERIVES_FROM edge exists
        edges = builder.get_edges_for_node("ko-x")
        derives = [e for e in edges if e.type == EdgeType.DERIVES_FROM]
        assert len(derives) == 1
        assert derives[0].source_id == doc_id
        assert derives[0].target_id == "ko-x"

    def test_no_provenance_no_derives_from(self, builder):
        from src.knowledge.core.object import (
            KnowledgeObject,
            KnowledgeType,
            LifecycleState,
            Provenance,
        )

        obj = KnowledgeObject(
            id="ko-no-prov", type=KnowledgeType.CONCEPT, title="No Prov",
            content="c", lifecycle=LifecycleState.CREATED, confidence=0.5,
            provenance=Provenance(source_path=""),  # empty source_path
            relations=[],
        )
        builder.build_from_objects([obj])

        edges = builder.get_edges_for_node("ko-no-prov")
        derives = [e for e in edges if e.type == EdgeType.DERIVES_FROM]
        assert len(derives) == 0


# ---------------------------------------------------------------------------
# 11. add_claim_with_evidence
# ---------------------------------------------------------------------------


class TestAddClaimWithEvidence:
    def test_creates_claim_node_and_derives_from_edges(self, builder):
        from src.knowledge.claims.model import Claim, ClaimType, ClaimStatus

        claim = Claim(
            id="claim-1",
            statement="The system is reliable.",
            type=ClaimType.FACT,
            confidence=0.95,
            status=ClaimStatus.VERIFIED,
            source_objects=["ko-src-1", "ko-src-2"],
        )
        builder.add_claim_with_evidence(claim, knowledge_object_id="ko-src-1")

        # Claim node exists
        node = builder.get_node("claim-1")
        assert node is not None
        assert node.type == NodeType.CLAIM
        assert node.label == "The system is reliable."
        assert node.properties["confidence"] == 0.95
        assert node.properties["status"] == "verified"
        assert node.properties["claim_type"] == "fact"

        # DERIVES_FROM edges from source objects to claim
        edges = builder.get_edges_for_node("claim-1")
        derives = [e for e in edges if e.type == EdgeType.DERIVES_FROM]
        assert len(derives) == 2
        source_ids = {e.source_id for e in derives}
        assert source_ids == {"ko-src-1", "ko-src-2"}

    def test_creates_evidence_nodes_and_supports_edges(self, builder):
        from src.knowledge.claims.model import Claim, ClaimType, ClaimStatus, Evidence

        claim = Claim(
            id="claim-ev",
            statement="Evidence-backed claim.",
            type=ClaimType.FACT,
            confidence=0.8,
            status=ClaimStatus.PENDING,
            evidence=[
                Evidence(source_path="/docs/ev1.pdf", page=3, quote="Lorem ipsum"),
            ],
            source_objects=[],
        )
        builder.add_claim_with_evidence(claim, knowledge_object_id="ko-x")

        # Evidence node created
        evidence_node_id = "claim-ev--evidence--0"
        ev_node = builder.get_node(evidence_node_id)
        assert ev_node is not None
        assert ev_node.type == NodeType.DOCUMENT

        # SUPPORTS edge from evidence to claim
        edges = builder.get_edges_for_node("claim-ev")
        supports = [e for e in edges if e.type == EdgeType.SUPPORTS]
        assert len(supports) == 1
        assert supports[0].source_id == evidence_node_id
        assert supports[0].target_id == "claim-ev"


# ---------------------------------------------------------------------------
# 12. add_conflict_edge
# ---------------------------------------------------------------------------


class TestAddConflictEdge:
    def test_creates_contradicts_edge(self, builder):
        builder.add_node(_make_node("claim-a", NodeType.CLAIM, "Claim A"))
        builder.add_node(_make_node("claim-b", NodeType.CLAIM, "Claim B"))
        builder.add_conflict_edge("claim-a", "claim-b")

        edge = builder.get_edge("claim-a--contradicts--claim-b")
        assert edge is not None
        assert edge.type == EdgeType.CONTRADICTS
        assert edge.source_id == "claim-a"
        assert edge.target_id == "claim-b"


# ---------------------------------------------------------------------------
# 13. Snapshot rebuild
# ---------------------------------------------------------------------------


class TestSnapshotRebuild:
    def test_rebuild_and_restore(self, wiki_paths):
        """Add nodes, rebuild snapshot, create new GraphBuilder → state restored."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("n1", NodeType.ENTITY, "Node1"))
        gb1.add_node(_make_node("n2", NodeType.CONCEPT, "Node2"))
        gb1.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "n1", "n2"))
        gb1.rebuild_snapshot()

        # New builder from same paths should restore state from snapshot
        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("n1") is not None
        assert gb2.get_node("n2") is not None
        assert gb2.get_edge("e1") is not None

        assert gb2.get_node("n1").label == "Node1"
        assert gb2.get_node("n2").type == NodeType.CONCEPT

    def test_snapshot_stored_at_correct_path(self, wiki_paths, builder):
        builder.add_node(_make_node("x"))
        builder.rebuild_snapshot()
        snapshot_path = wiki_paths.index / "knowledge_graph" / "snapshot.json"
        assert snapshot_path.exists()

        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "nodes" in data
        assert "edges" in data
        assert "total_events" in data
        assert len(data["nodes"]) == 1


# ---------------------------------------------------------------------------
# 14. Events replay
# ---------------------------------------------------------------------------


class TestEventsReplay:
    def test_replay_restores_state(self, wiki_paths):
        """Add nodes (append events), create new GraphBuilder → events replayed."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("a", NodeType.ENTITY, "A"))
        gb1.add_node(_make_node("b", NodeType.CONCEPT, "B"))
        gb1.add_edge(_make_edge("e", EdgeType.RELATES_TO, "a", "b"))

        # New builder replays events
        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("a") is not None
        assert gb2.get_node("b") is not None
        assert gb2.get_edge("e") is not None
        assert gb2.get_node("a").label == "A"

    def test_snapshot_plus_replay(self, wiki_paths):
        """Snapshot + new events → both snapshot and replay contribute."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("snap-node", NodeType.ENTITY, "Snap"))
        gb1.rebuild_snapshot()

        # Add event AFTER snapshot
        gb1.add_node(_make_node("replay-node", NodeType.CONCEPT, "Replay"))

        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("snap-node") is not None
        assert gb2.get_node("replay-node") is not None


# ---------------------------------------------------------------------------
# 15. Auto snapshot trigger (100+ events)
# ---------------------------------------------------------------------------


class TestAutoSnapshotTrigger:
    def test_triggers_after_threshold(self, wiki_paths):
        """Add 100+ events → snapshot auto-rebuilt (counter reset)."""
        gb = GraphBuilder(wiki_paths)

        # Add exactly 100 nodes to trigger auto-snapshot
        for i in range(100):
            gb.add_node(_make_node(f"n{i}", NodeType.ENTITY, f"Node{i}"))

        # After 100 events, snapshot should have been rebuilt
        # _event_count_since_snapshot should be 0 (reset after rebuild)
        assert gb._event_count_since_snapshot == 0

        # Snapshot file should exist
        snapshot_path = wiki_paths.index / "knowledge_graph" / "snapshot.json"
        assert snapshot_path.exists()

        # New builder loaded from snapshot should have all 100 nodes
        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("n0") is not None
        assert gb2.get_node("n99") is not None

    def test_no_trigger_below_threshold(self, wiki_paths):
        """Only 50 events → snapshot NOT auto-rebuilt."""
        gb = GraphBuilder(wiki_paths)
        for i in range(50):
            gb.add_node(_make_node(f"n{i}", NodeType.ENTITY, f"Node{i}"))

        # 50 < 100, so _event_count_since_snapshot should be 50
        assert gb._event_count_since_snapshot == 50


# ---------------------------------------------------------------------------
# 16. delete_node event in replay
# ---------------------------------------------------------------------------


class TestDeleteNodeEventReplay:
    def test_node_gone_after_replay(self, wiki_paths):
        """Add node, then delete, replay → node is gone."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("delnode", NodeType.ENTITY, "DelMe"))
        gb1.remove_node("delnode")

        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("delnode") is None

    def test_delete_node_cascades_edges_in_replay(self, wiki_paths):
        """Delete node event replays with cascade edge removal."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("a"))
        gb1.add_node(_make_node("b"))
        gb1.add_edge(_make_edge("edge-ab", EdgeType.RELATES_TO, "a", "b"))
        gb1.remove_node("a")

        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_node("a") is None
        assert gb2.get_edge("edge-ab") is None
        # b survives
        assert gb2.get_node("b") is not None


# ---------------------------------------------------------------------------
# 17. delete_edge event in replay
# ---------------------------------------------------------------------------


class TestDeleteEdgeEventReplay:
    def test_edge_gone_after_replay(self, wiki_paths):
        """Add edge, then delete, replay → edge is gone."""
        gb1 = GraphBuilder(wiki_paths)
        gb1.add_node(_make_node("a"))
        gb1.add_node(_make_node("b"))
        gb1.add_edge(_make_edge("del-edge", EdgeType.RELATES_TO, "a", "b"))
        gb1.remove_edge("del-edge")

        gb2 = GraphBuilder(wiki_paths)
        assert gb2.get_edge("del-edge") is None
        assert gb2.get_node("a") is not None  # nodes unaffected


# ---------------------------------------------------------------------------
# 18. NodeType enum values
# ---------------------------------------------------------------------------


class TestNodeTypeEnum:
    def test_all_six_values(self):
        assert NodeType.ENTITY.value == "entity"
        assert NodeType.CONCEPT.value == "concept"
        assert NodeType.CLAIM.value == "claim"
        assert NodeType.DECISION.value == "decision"
        assert NodeType.DOCUMENT.value == "document"
        assert NodeType.EVENT.value == "event"

    def test_count_is_six(self):
        members = list(NodeType)
        assert len(members) == 6, f"Expected 6, got {len(members)}: {[m.value for m in members]}"

    def test_deserialize_from_string(self):
        assert NodeType("entity") == NodeType.ENTITY
        assert NodeType("concept") == NodeType.CONCEPT
        assert NodeType("claim") == NodeType.CLAIM
        assert NodeType("decision") == NodeType.DECISION
        assert NodeType("document") == NodeType.DOCUMENT
        assert NodeType("event") == NodeType.EVENT


# ---------------------------------------------------------------------------
# 19. EdgeType enum values
# ---------------------------------------------------------------------------


class TestEdgeTypeEnum:
    def test_all_five_values(self):
        assert EdgeType.SUPPORTS.value == "supports"
        assert EdgeType.CONTRADICTS.value == "contradicts"
        assert EdgeType.DERIVES_FROM.value == "derives_from"
        assert EdgeType.RELATES_TO.value == "relates_to"
        assert EdgeType.PRECEDES.value == "precedes"

    def test_count_is_five(self):
        members = list(EdgeType)
        assert len(members) == 5, f"Expected 5, got {len(members)}: {[m.value for m in members]}"

    def test_deserialize_from_string(self):
        assert EdgeType("supports") == EdgeType.SUPPORTS
        assert EdgeType("contradicts") == EdgeType.CONTRADICTS
        assert EdgeType("derives_from") == EdgeType.DERIVES_FROM
        assert EdgeType("relates_to") == EdgeType.RELATES_TO
        assert EdgeType("precedes") == EdgeType.PRECEDES


# ---------------------------------------------------------------------------
# 20. query() returns dict
# ---------------------------------------------------------------------------


class TestQuery:
    def test_returns_correct_structure(self, builder):
        builder.add_node(_make_node("n1", NodeType.ENTITY, "E1"))
        builder.add_node(_make_node("n2", NodeType.CONCEPT, "C2"))
        builder.add_edge(_make_edge("e1", EdgeType.RELATES_TO, "n1", "n2"))

        result = builder.query()
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)

    def test_empty_graph_query(self, builder):
        result = builder.query()
        assert result == {"nodes": [], "edges": []}

    def test_query_reflects_current_state(self, builder):
        builder.add_node(_make_node("x"))
        result = builder.query()
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "x"

        builder.add_node(_make_node("y"))
        result = builder.query()
        assert len(result["nodes"]) == 2


# ---------------------------------------------------------------------------
# GraphNode / GraphEdge serialization
# ---------------------------------------------------------------------------


class TestGraphNodeSerialization:
    def test_to_dict_and_from_dict_roundtrip(self):
        node = GraphNode(
            id="n1", type=NodeType.ENTITY, label="Test",
            properties={"key": "value", "num": 42},
        )
        d = node.to_dict()
        restored = GraphNode.from_dict(d)
        assert restored.id == node.id
        assert restored.type == node.type
        assert restored.label == node.label
        assert restored.properties == node.properties

    def test_from_dict_minimal(self):
        d = {"id": "min", "type": "entity", "label": "Min"}
        node = GraphNode.from_dict(d)
        assert node.id == "min"
        assert node.type == NodeType.ENTITY
        assert node.label == "Min"
        assert node.properties == {}


class TestGraphEdgeSerialization:
    def test_to_dict_and_from_dict_roundtrip(self):
        edge = GraphEdge(
            id="e1", type=EdgeType.SUPPORTS,
            source_id="a", target_id="b",
            properties={"weight": 0.8},
        )
        d = edge.to_dict()
        restored = GraphEdge.from_dict(d)
        assert restored.id == edge.id
        assert restored.type == edge.type
        assert restored.source_id == edge.source_id
        assert restored.target_id == edge.target_id
        assert restored.properties == edge.properties

    def test_from_dict_minimal(self):
        d = {"id": "e", "type": "relates_to", "source_id": "s", "target_id": "t"}
        edge = GraphEdge.from_dict(d)
        assert edge.id == "e"
        assert edge.type == EdgeType.RELATES_TO
        assert edge.source_id == "s"
        assert edge.target_id == "t"
        assert edge.properties == {}
