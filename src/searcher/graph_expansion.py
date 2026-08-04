"""Graph expansion retrieval — 4-Signal relevance model.

Implements Nash's graph expansion approach to improve recall by traversing
the knowledge graph and scoring page relevance beyond pure vector similarity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...wiki.core.types import WikiPage
    from ...wiki.core.paths import WikiPaths


class RelevanceSignal(str, Enum):
    """4-Signal relevance model from Nash."""

    DIRECT_LINK = "direct_link"       # [[wikilink]] from A to B
    SOURCE_OVERLAP = "source_overlap"  # Shared source documents
    ADAMIC_ADAR = "adamic_adar"        # Common neighbors weighted by inverse degree
    TYPE_AFFINITY = "type_affinity"    # Same page type (entity/concept/etc)


@dataclass
class RelevanceScore:
    """Scored page with breakdown by signal."""

    page_id: str
    score: float
    signals: dict[RelevanceSignal, float]


# Signal weights (from Nash config)
SIGNAL_WEIGHTS: dict[RelevanceSignal, float] = {
    RelevanceSignal.DIRECT_LINK: 3.0,
    RelevanceSignal.SOURCE_OVERLAP: 4.0,
    RelevanceSignal.ADAMIC_ADAR: 1.5,
    RelevanceSignal.TYPE_AFFINITY: 1.0,
}


def compute_adamic_adar(
    neighbors_a: set[str],
    neighbors_b: set[str],
    degree_map: dict[str, int],
) -> float:
    """Compute Adamic-Adar similarity between two nodes.

    Adamic-Adar: sum over common neighbors of 1/log(degree)

    Args:
        neighbors_a: Neighbors of node A
        neighbors_b: Neighbors of node B
        degree_map: Node ID → degree mapping

    Returns:
        Adamic-Adar score (higher = more similar)
    """
    common = neighbors_a & neighbors_b
    if not common:
        return 0.0

    score = 0.0
    for node in common:
        degree = degree_map.get(node, 1)
        if degree > 1:
            score += 1.0 / math.log(degree)

    return score


def build_graph_index(pages: list["WikiPage"]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, int]]:
    """Build graph indexes for relevance computation.

    Returns:
        (adjacency_map, source_overlap_map, degree_map)
        - adjacency_map: page_id → set of linked page_ids
        - source_overlap_map: source_path → set of page_ids
        - degree_map: page_id → degree (number of connections)
    """
    adjacency: dict[str, set[str]] = {}
    source_to_pages: dict[str, set[str]] = {}
    degree: dict[str, int] = {}

    # Build adjacency from relations
    for page in pages:
        page_id = page.id
        if page_id not in adjacency:
            adjacency[page_id] = set()

        for rel in page.relations:
            target_id = getattr(rel, "target_id", None) or getattr(rel, "target", "")
            if target_id:
                adjacency[page_id].add(target_id)
                # Also add reverse link
                if target_id not in adjacency:
                    adjacency[target_id] = set()
                adjacency[target_id].add(page_id)

        # Track source overlap
        for src in page.sources:
            if src not in source_to_pages:
                source_to_pages[src] = set()
            source_to_pages[src].add(page_id)

    # Compute degrees
    for page_id, neighbors in adjacency.items():
        degree[page_id] = len(neighbors)

    return adjacency, source_to_pages, degree


def expand_with_graph(
    seed_page_ids: list[str],
    adjacency: dict[str, set[str]],
    source_overlap: dict[str, set[str]],
    degree: dict[str, int],
    page_types: dict[str, str],
    max_depth: int = 2,
    decay: float = 0.5,
) -> list[RelevanceScore]:
    """Expand from seed pages using graph traversal and relevance scoring.

    Args:
        seed_page_ids: Starting pages from vector/keyword search
        adjacency: page_id → linked page_ids
        source_overlap: source_path → page_ids
        degree: page_id → degree
        page_types: page_id → type string
        max_depth: Maximum traversal depth (default 2-hop)
        decay: Score decay per hop (default 0.5)

    Returns:
        List of RelevanceScore for expanded pages, sorted by score
    """
    scores: dict[str, RelevanceScore] = {}

    # Seed pages get base score
    for page_id in seed_page_ids:
        scores[page_id] = RelevanceScore(
            page_id=page_id,
            score=1.0,
            signals={},
        )

    # BFS traversal
    visited = set(seed_page_ids)
    frontier = set(seed_page_ids)

    for depth in range(1, max_depth + 1):
        next_frontier = set()

        for node in frontier:
            neighbors = adjacency.get(node, {})
            for neighbor in neighbors:
                if neighbor in visited:
                    continue

                visited.add(neighbor)
                next_frontier.add(neighbor)

                # Compute relevance signals
                signals: dict[RelevanceSignal, float] = {}

                # Signal 1: Direct link
                if neighbor in adjacency.get(node, set()):
                    signals[RelevanceSignal.DIRECT_LINK] = SIGNAL_WEIGHTS[RelevanceSignal.DIRECT_LINK]

                # Signal 2: Source overlap (computed via shared sources)
                # This requires additional index - skip for now

                # Signal 3: Adamic-Adar
                aa_score = compute_adamic_adar(
                    adjacency.get(node, set()),
                    adjacency.get(neighbor, set()),
                    degree,
                )
                if aa_score > 0:
                    signals[RelevanceSignal.ADAMIC_ADAR] = aa_score * SIGNAL_WEIGHTS[RelevanceSignal.ADAMIC_ADAR]

                # Signal 4: Type affinity
                node_type = page_types.get(node, "")
                neighbor_type = page_types.get(neighbor, "")
                if node_type and neighbor_type and node_type == neighbor_type:
                    signals[RelevanceSignal.TYPE_AFFINITY] = SIGNAL_WEIGHTS[RelevanceSignal.TYPE_AFFINITY]

                # Total score with depth decay
                total_score = sum(signals.values()) * (decay ** depth)

                if neighbor not in scores or total_score > scores[neighbor].score:
                    scores[neighbor] = RelevanceScore(
                        page_id=neighbor,
                        score=total_score,
                        signals=signals,
                    )

        frontier = next_frontier
        if not frontier:
            break

    # Sort by score
    return sorted(scores.values(), key=lambda s: s.score, reverse=True)


def hybrid_search_with_graph(
    seed_results: list[str],
    pages: list["WikiPage"],
    top_k: int = 20,
) -> list[RelevanceScore]:
    """Combine vector search results with graph expansion.

    Args:
        seed_results: Page IDs from vector/keyword search
        pages: All wiki pages for graph building
        top_k: Number of results to return

    Returns:
        Expanded and re-ranked results
    """
    # Build indexes
    adjacency, source_overlap, degree = build_graph_index(pages)
    page_types = {p.id: p.type.value if hasattr(p.type, "value") else str(p.type) for p in pages}

    # Expand with graph
    expanded = expand_with_graph(
        seed_page_ids=seed_results,
        adjacency=adjacency,
        source_overlap=source_overlap,
        degree=degree,
        page_types=page_types,
    )

    return expanded[:top_k]