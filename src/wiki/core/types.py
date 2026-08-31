"""Wiki core types — page model, events, tasks, review items."""
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..features.relations import Relation


def _format_legacy_evidence(item: dict) -> str:
    """Convert one legacy ``_ko_extra.evidence`` entry to the new
    ``evidence_refs`` string format.

    ``{"doc_id": "d1", "block_id": "b1"}`` → ``"d1:b1"``
    ``{"doc_id": "d1"}`` (no block_id) → ``"d1"``

    Falls back to the raw stringification of the dict when neither key is
    present so we never raise on weird legacy data.
    """
    doc_id = item.get("doc_id")
    block_id = item.get("block_id")
    if doc_id and block_id:
        return f"{doc_id}:{block_id}"
    if doc_id:
        return str(doc_id)
    return str(item)


class PageType(str, Enum):
    """V4 strict whitelist — only 4 page types."""
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    SYNTHESIS = "synthesis"


_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
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
    # Decision record payload (migrated from _ko_extra.memory.decision in C-0
    # Commit 2). ``None`` when no decision data is attached.
    decision_record: dict | None = None
    # Evidence refs (migrated from _ko_extra.evidence in C-0 Commit 4).
    # String list of ``"<doc_id>:<block_id>"`` (or ``"<doc_id>"`` when the
    # legacy entry had no block_id). Empty when no evidence is attached.
    evidence_refs: list[str] = field(default_factory=list)
    # Task 6 (plan 2026-08-29-...): temporal validity window. Both None
    # is treated as "unknown" (back-compat default for legacy pages with
    # no temporal fields). The interval is half-open [valid_from,
    # valid_to) per spec §10. Additive — pages written before this
    # field existed round-trip cleanly via ``from_dict`` (defaults
    # preserve the legacy unknown state).
    valid_from: int | None = None
    valid_to: int | None = None

    def to_frontmatter_dict(self) -> dict:
        """Serialize the page to a V4 8-key strict-whitelist frontmatter dict.

        V4 schema (per docs/architecture/novel-wiki-fields-template-2026-08-31.md):
            id, title, type, relations, tags, sources, created_at, updated_at

        All other fields (grade/processing_depth/heat/workflow_state/
        decision_record/evidence_refs/valid_from/valid_to/_ko_extra/...) are
        kept on the in-memory dataclass for backward compatibility with code
        that constructs WikiPage objects directly, but are NOT written to
        disk. The 8 V4 keys are the only contract between WikiPage and the
        on-disk frontmatter.
        """
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "sources": list(self.sources),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "relations": [r.to_dict() for r in self.relations],
            "tags": list(self.tags),
        }

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
            decision_record=d.get("decision_record"),
            evidence_refs=list(d.get("evidence_refs", []) or []),
            valid_from=d.get("valid_from"),
            valid_to=d.get("valid_to"),
        )
        # S1: restore _ko_extra for round-trip (capture source_status, etc.)
        ko_extra = d.get("_ko_extra")
        if isinstance(ko_extra, dict):
            # C-0 Commit 1: migrate _ko_extra.source_status to workflow_state.
            # The legacy key may appear on pages written before the migration;
            # lift its value to the top-level workflow_state field and drop
            # the key from _ko_extra so the canonical home is now workflow_state.
            legacy_source_status = ko_extra.pop("source_status", None)
            if legacy_source_status is not None and page.workflow_state == "draft":
                page.workflow_state = str(legacy_source_status)
            # C-0 Commit 2: migrate _ko_extra.memory.decision to decision_record.
            # If the explicit top-level field was absent, lift the legacy
            # payload into it (so reads see it) but keep _ko_extra around for
            # back-compat round-trip of unrelated legacy keys
            # (e.g. capture_context).
            if page.decision_record is None:
                memory = ko_extra.get("memory")
                if isinstance(memory, dict):
                    legacy_decision = memory.get("decision")
                    if isinstance(legacy_decision, dict):
                        page.decision_record = legacy_decision
            # C-0 Commit 4: migrate _ko_extra.evidence → evidence_refs.
            # Only when the explicit top-level field is absent/empty — the
            # explicit value wins. Legacy entries (list of dicts with
            # ``doc_id`` / optional ``block_id``) format as
            # ``"<doc_id>:<block_id>"`` or ``"<doc_id>"``.
            if not page.evidence_refs:
                legacy_evidence = ko_extra.get("evidence")
                if isinstance(legacy_evidence, list):
                    page.evidence_refs = [
                        _format_legacy_evidence(item)
                        for item in legacy_evidence
                        if isinstance(item, dict)
                    ]
            page._ko_extra = ko_extra
        return page


# V4 has no workflow_state / processing_depth fields — they were removed
# from the frontmatter schema in 2026-08-31. The in-memory dataclass still
# keeps them for backward compatibility with code that constructs WikiPage
# objects directly, but they are never written to disk. See ADR-002.

# These two constants are kept for the legacy lint path — pages written by
# pre-V4 pipelines still carry these fields in their frontmatter. The lint
# uses these to flag invalid legacy values. New writes never include them.
VALID_WORKFLOW_STATES = frozenset({"draft", "ready", "verified", "outdated"})
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
