"""Typed relations between wiki pages (bidirectional)."""
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class RelationType(str, Enum):
    IS_PART_OF = "is_part_of"
    CONTAINS = "contains"
    REFERENCES = "references"
    REFERENCED_BY = "referenced_by"
    CAUSES = "causes"
    CAUSED_BY = "caused_by"
    CONTRADICTS = "contradicts"     # symmetric
    SUPPORTS = "supports"
    SUPPORTED_BY = "supported_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    DEPENDS_ON = "depends_on"
    REQUIRED_BY = "required_by"
    ANALOGOUS_TO = "analogous_to"   # symmetric
    OPPOSITE_OF = "opposite_of"     # symmetric
    DERIVED_FROM = "derived_from"
    DERIVES = "derives"


# Inverse relation table
INVERSE_RELATIONS = {
    "is_part_of": "contains",
    "contains": "is_part_of",
    "references": "referenced_by",
    "referenced_by": "references",
    "causes": "caused_by",
    "caused_by": "causes",
    "contradicts": "contradicts",       # symmetric
    "supports": "supported_by",
    "supported_by": "supports",
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "depends_on": "required_by",
    "required_by": "depends_on",
    "analogous_to": "analogous_to",     # symmetric
    "opposite_of": "opposite_of",       # symmetric
    "derived_from": "derives",
    "derives": "derived_from",
}

USER_TYPE_PREFIX = "x-"


@dataclass
class Relation:
    target_id: str
    type: str                # RelationType.value or f"x-{name}"
    weight: float = 1.0
    context: str = ""

    def to_dict(self) -> dict:
        return {"target": self.target_id, "type": self.type,
                "weight": round(self.weight, 2), "context": self.context}

    @classmethod
    def from_dict(cls, d: dict) -> "Relation":
        # B12: normalise the target to the same slug form used for page ids
        # (the generator slugifies page ids via utils.slugify). Without this,
        # a relation target emitted as a raw/human string and a page id
        # derived from the same string diverge, producing dangling
        # relations. Idempotent when the target is already slugified.
        from ...utils.slugify import slugify as _slugify
        return cls(
            target_id=_slugify(d["target"]) or d["target"], type=d["type"],
            weight=d.get("weight", 1.0), context=d.get("context", ""),
        )

    def inverse(self) -> Optional["Relation"]:
        inv_type = INVERSE_RELATIONS.get(self.type)
        if inv_type is None:
            return None
        return Relation(target_id="<this_page_id>", type=inv_type, weight=self.weight, context=self.context)


def parse_relations_from_response(relations_raw: list[dict]) -> list["Relation"]:
    """Convert raw LLM response dicts to Relation instances."""
    return [Relation.from_dict(r) for r in relations_raw if r]


SYMMETRIC_RELATIONS = frozenset({"contradicts", "analogous_to", "opposite_of"})


@dataclass
class SyncReport:
    page_id: str
    added: list[Relation] = field(default_factory=list)
    updated: list[Relation] = field(default_factory=list)


def _infer_type(paths, slug: str):
    """Find which subdir contains the page. Defaults to SOURCE if not found."""
    from ..core.types import PageType
    for type_, dir_prop in [
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SOURCE, "wiki_sources"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
    ]:
        if (getattr(paths, dir_prop) / f"{slug}.md").exists():
            return type_
    return PageType.SOURCE


class RelationSync:
    """Bidirectional sync of relations in wiki/."""

    @staticmethod
    def sync_page(paths, page_id: str, relations: list[Relation]) -> SyncReport:
        """Write relations to page; apply inverse relations to target pages."""
        from ..storage.page_writer import read_page, write_page
        from ..storage.page_writer import page_path_for
        from ..core.types import PageType

        report = SyncReport(page_id=page_id)
        # Load page
        page_type = _infer_type(paths, page_id)
        page_file = page_path_for(paths, page_type, page_id)
        if not page_file.exists():
            return report
        page = read_page(page_file)
        # Update page's relations
        page.relations = relations
        write_page(paths, page)
        report.added = relations
        # Apply inverse to each target
        for rel in relations:
            inv = rel.inverse()
            if inv is None or rel.type in SYMMETRIC_RELATIONS:
                continue  # symmetric; already added or skip duplicates
            inv.target_id = page_id
            target_type = _infer_type(paths, rel.target_id)
            target_file = page_path_for(paths, target_type, rel.target_id)
            if not target_file.exists():
                continue
            target_page = read_page(target_file)
            if any(r.target_id == page_id and r.type == inv.type for r in target_page.relations):
                continue  # already has inverse
            target_page.relations.append(inv)
            write_page(paths, target_page)
        return report


class RelationQuery:
    """Read-side queries over relations."""

    @staticmethod
    def list_relations(paths, page_id: str) -> list[Relation]:
        from ..storage.page_writer import read_page
        from ..storage.page_writer import page_path_for
        from ..core.types import PageType  # noqa: F401  (kept for symmetry / potential use)
        page_type = _infer_type(paths, page_id)
        page_file = page_path_for(paths, page_type, page_id)
        if not page_file.exists():
            return []
        return read_page(page_file).relations

    @staticmethod
    def find_backlinks(paths, page_id: str) -> list[Relation]:
        """Scan all wiki pages for relations where target == page_id."""
        from ..storage.page_writer import read_page
        from ..core.types import PageType
        backlinks: list[Relation] = []
        for type_, dir_prop in [
            (PageType.SOURCE, "wiki_sources"),
            (PageType.ENTITY, "wiki_entities"),
            (PageType.CONCEPT, "wiki_concepts"),
            (PageType.SYNTHESIS, "wiki_synthesis"),
        ]:
            for f in getattr(paths, dir_prop).glob("*.md"):
                page = read_page(f)
                for rel in page.relations:
                    if rel.target_id == page_id:
                        backlinks.append(Relation(
                            target_id=page.id, type=rel.type,
                            weight=rel.weight, context=rel.context,
                        ))
        return backlinks

    @staticmethod
    def find_neighbors(paths, page_id: str, depth: int = 1) -> list[tuple[str, str, float]]:
        """BFS up to `depth` hops. Returns (neighbor_id, via_relation, cumulative_weight)."""
        from collections import deque
        visited = {page_id}
        queue = deque([(page_id, [], 1.0)])
        results: list[tuple[str, str, float]] = []
        while queue:
            current, path, weight = queue.popleft()
            if len(path) > depth:
                continue
            relations = RelationQuery.list_relations(paths, current)
            for rel in relations:
                if rel.target_id in visited:
                    continue
                visited.add(rel.target_id)
                new_weight = weight * rel.weight
                results.append((rel.target_id, rel.type, new_weight))
                if len(path) + 1 < depth:
                    queue.append((rel.target_id, path + [rel], new_weight))
        return results

    @staticmethod
    def find_path(paths, source_id: str, target_id: str) -> list[tuple[str, str, str]]:
        """BFS shortest path. Returns [(from_id, to_id, relation_type), ...] edges."""
        from collections import deque
        if source_id == target_id:
            return []
        visited = {source_id}
        queue = deque([(source_id, [])])
        while queue:
            current, path = queue.popleft()
            relations = RelationQuery.list_relations(paths, current)
            for rel in relations:
                if rel.target_id in visited:
                    continue
                if rel.target_id == target_id:
                    return path + [(current, rel.target_id, rel.type)]
                visited.add(rel.target_id)
                queue.append((rel.target_id, path + [(current, rel.target_id, rel.type)]))
        return []  # no path