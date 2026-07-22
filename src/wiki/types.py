"""Wiki core types — page model, events, tasks, review items."""
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .relations import Relation


class PageType(str, Enum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    SYNTHESIS = "synthesis"


class EventName:
    TASK_CREATED = "task:created"
    TASK_STATUS_CHANGED = "task:status:changed"
    COLLECTOR_DONE = "collector:done"
    ANALYZER_DONE = "analyzer:done"
    GENERATOR_DONE = "generator:done"
    QUALITY_JUDGED = "quality:judged"
    LIBRARIAN_DONE = "librarian:done"
    REVIEW_RESOLVED = "review:resolved"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    ARCHIVED = "archived"


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

    def to_frontmatter_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "sources": list(self.sources),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "relations": [r.to_dict() for r in self.relations],
        }

    @classmethod
    def from_dict(cls, d: dict, body: str = "") -> "WikiPage":
        from .relations import Relation
        return cls(
            id=d["id"],
            title=d["title"],
            type=PageType(d["type"]),
            sources=list(d.get("sources", [])),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
            body=body,
            relations=[Relation.from_dict(r) for r in d.get("relations", [])],
        )


@dataclass
class KnowledgeTask:
    id: str
    source: str
    source_type: str
    status: TaskStatus
    task_hash: str
    created_at: int
    updated_at: int
    retry_count: int = 0
    error: Optional[str] = None
    wiki_pages: list[str] = field(default_factory=list)
    folder_context: str = ""


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
