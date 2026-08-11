"""Wiki core types — page model, events, tasks, review items."""
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..features.relations import Relation


def _ms_to_date(ms: int) -> str:
    """Convert unix ms timestamp to YYYY-MM-DD string. Returns '' for 0."""
    if not ms:
        return ""
    from datetime import datetime
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _date_to_ms(date_str: str) -> int:
    """Convert YYYY-MM-DD string to unix ms timestamp. Returns 0 for empty/invalid."""
    if not date_str:
        return 0
    try:
        from datetime import datetime
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    SYNTHESIS = "synthesis"


@dataclass
class WikiPage:
    id: str
    title: str
    type: PageType
    sources: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    relations: list["Relation"] = field(default_factory=list)
    # NEW v2.2 fields
    grade: str = "B"                       # "A" | "B" | "C"
    processing_depth: str = "concept"      # "concept" | "memory"
    is_immutable: bool = False
    # NEW heat fields (wiki-heat-5pool T1)
    heat: int = 50
    last_used_at: str = ""
    zombie_since: str = ""
    # Tags: controlled namespace prefixes (e.g. char/女主角, genre/都市)
    tags: list[str] = field(default_factory=list)
    # Taxonomy (v3.1): LLM-assigned classification, "" = unclassified
    category: str = ""
    taxonomy_sub: str = ""

    def to_frontmatter_dict(self) -> dict:
        return {
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
        }

    @classmethod
    def from_dict(cls, d: dict, body: str = "") -> "WikiPage":
        from ..features.relations import Relation
        return cls(
            id=d["id"],
            title=d["title"],
            type=PageType(d["type"]),
            sources=list(d.get("sources", [])),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
            body=body,
            relations=[Relation.from_dict(r) for r in d.get("relations", []) if isinstance(r, dict)],
            grade=d.get("grade", "B"),
            processing_depth=d.get("processing_depth", "concept"),
            is_immutable=d.get("is_immutable", False),
            heat=d.get("heat", 50),
            last_used_at=str(d.get("last_used_at", "") or ""),
            zombie_since=str(d.get("zombie_since", "") or ""),
            tags=list(d.get("tags", [])),
            category=d.get("category", ""),
            taxonomy_sub=d.get("taxonomy_sub", ""),
        )


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
