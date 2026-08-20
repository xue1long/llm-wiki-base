"""Wiki core types — page model, events, tasks, review items."""
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..features.relations import Relation


class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    SYNTHESIS = "synthesis"
    CLAIM = "claim"
    DECISION = "decision"
    PROCEDURE = "procedure"
    EVENT = "event"


_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
    PageType.CLAIM: "wiki_claims",
    PageType.DECISION: "wiki_decisions",
    PageType.PROCEDURE: "wiki_concepts",
    PageType.EVENT: "wiki_concepts",
}


@dataclass
class WikiPage:
    id: str
    title: str
    type: PageType
    sources: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    body: str = ""
    relations: list["Relation"] = field(default_factory=list)
    # NEW v2.2 fields
    grade: str = "B"                       # "A" | "B" | "C"
    processing_depth: str = "concept"      # "concept" | "memory" | "operation"
    is_immutable: bool = False
    # NEW heat fields (wiki-heat-5pool T1)
    heat: int = 50
    last_used_at: int = 0
    zombie_since: int | None = None
    # Tags: controlled namespace prefixes (e.g. char/女主角, genre/都市)
    tags: list[str] = field(default_factory=list)
    # Taxonomy (v3.1): LLM-assigned classification, "" = unclassified
    category: str = ""
    taxonomy_sub: str = ""
    # C3: low-importance entity references inlined instead of creating stub pages
    related_entities: list[str] = field(default_factory=list)
    # Custom page type name (from schema.md), e.g. "thesis". Empty for
    # built-in types. When set, the page routes to wiki/<custom>/ instead
    # of the base type's dir; ``type`` stays the base enum for rendering.
    custom_type: str = ""
    # Workflow state (draft/ready/verified/outdated), default draft (compat).
    workflow_state: str = "draft"
    # Unix-ms timestamp of last human verification; 0 = never verified.
    verified_at: int = 0

    def to_frontmatter_dict(self) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "sources": list(self.sources),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "relations": [r.to_dict() for r in self.relations],
            "grade": self.grade,
            "processing_depth": self.processing_depth,
            "is_immutable": self.is_immutable,
            "heat": self.heat,
            "last_used_at": self.last_used_at,
            "zombie_since": self.zombie_since,
            "tags": list(self.tags),
            "category": self.category,
            "taxonomy_sub": self.taxonomy_sub,
            "related_entities": list(self.related_entities),
            "custom_type": self.custom_type,
            "workflow_state": self.workflow_state,
            "verified_at": self.verified_at,
        }
        ko_extra = getattr(self, "_ko_extra", None)
        if isinstance(ko_extra, dict):
            d["_ko_extra"] = ko_extra
        return d

    @classmethod
    def from_dict(cls, d: dict, body: str = "") -> "WikiPage":
        from ..features.relations import Relation
        page = cls(
            id=d["id"],
            title=d["title"],
            type=PageType(d["type"]),
            sources=list(d.get("sources", [])),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
            body=body,
            relations=[Relation.from_dict(r) for r in d.get("relations", []) if isinstance(r, dict)],
            grade=d.get("grade", "B"),
            processing_depth=d.get("processing_depth", "concept"),
            is_immutable=d.get("is_immutable", False),
            heat=d.get("heat", 50),
            last_used_at=d.get("last_used_at", 0),
            zombie_since=d.get("zombie_since"),
            tags=list(d.get("tags", [])),
            category=d.get("category", ""),
            taxonomy_sub=d.get("taxonomy_sub", ""),
            related_entities=list(d.get("related_entities", [])),
            custom_type=str(d.get("custom_type", "")),
            workflow_state=str(d.get("workflow_state", "draft")),
            verified_at=int(d.get("verified_at", 0)),
        )
        # S1: restore _ko_extra for round-trip (capture source_status, etc.)
        ko_extra = d.get("_ko_extra")
        if isinstance(ko_extra, dict):
            page._ko_extra = ko_extra
        return page


# Valid values for workflow_state (lint reference).
VALID_WORKFLOW_STATES = frozenset({"draft", "ready", "verified", "outdated"})
# Valid values for processing_depth (lint reference).
VALID_PROCESSING_DEPTHS = frozenset({"concept", "memory", "operation"})


@dataclass
class ReviewItem:
    id: str
    type: str       # "missing-page" | "duplicate-page" | "uncertain-claim" | "needs-verification"
    title: str
    normalized_title: str
    detail: str
    confidence: float
    search_queries: list[str] = field(default_factory=list)
    page_path: Optional[str] = None
    created_at: int = 0
    source_task_id: Optional[str] = None
    status: str = "open"  # "open" | "resolved" | "dismissed"

    def __post_init__(self):
        """Auto-compute normalized_title if caller didn't supply one."""
        if not self.normalized_title:
            self.normalized_title = " ".join(self.title.lower().split())


def make_review_item(
    item_id: str, type_: str, title: str, detail: str, confidence: float = 1.0,
    search_queries: list[str] | None = None, page_path: str | None = None,
    created_at: int = 0, source_task_id: str | None = None, status: str = "open",
) -> ReviewItem:
    return ReviewItem(
        id=item_id,
        type=type_,
        title=title,
        normalized_title=" ".join(title.lower().split()),
        detail=detail,
        confidence=confidence,
        search_queries=list(search_queries or []),
        page_path=page_path,
        created_at=created_at,
        source_task_id=source_task_id,
        status=status,
    )


# Relation types historically lived in ``src.wiki.relations``.  Keep a lazy
# compatibility bridge here for callers that imported them from ``types``;
# deferring the import preserves the core -> features dependency direction.
_RELATION_EXPORTS = {
    "Relation",
    "RelationType",
    "RelationQuery",
    "RelationSync",
    "SyncReport",
    "parse_relations_from_response",
}


def __getattr__(name: str):
    if name in _RELATION_EXPORTS:
        from ..features import relations
        return getattr(relations, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
