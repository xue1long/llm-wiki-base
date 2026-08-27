"""Core knowledge data model — enums, provenance, and the KnowledgeObject dataclass."""
from dataclasses import dataclass, field
from enum import Enum


class KnowledgeType(str, Enum):
    """Knowledge object types — 1:1 with extended PageType."""

    DOCUMENT = "document"
    ENTITY = "entity"
    CONCEPT = "concept"
    CLAIM = "claim"
    DECISION = "decision"
    PROCEDURE = "procedure"
    EVENT = "event"
    SYNTHESIS = "synthesis"


class LifecycleState(str, Enum):
    """8-state lifecycle for knowledge objects."""

    CREATED = "created"
    PROCESSING = "processing"
    REVIEWING = "reviewing"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class Provenance:
    """Source provenance — where a piece of knowledge came from."""

    source_path: str
    page: int | None = None
    quote: str = ""
    ingested_at: int = 0
    ingestor_version: str = ""


@dataclass
class VersionRef:
    """Reference to a specific version of a KnowledgeObject."""

    version_id: str
    timestamp: int
    change_description: str = ""


@dataclass
class KnowledgeObject:
    """Core knowledge object — the primary data model for Knowledge OS."""

    id: str
    type: KnowledgeType
    title: str
    content: str
    lifecycle: LifecycleState
    confidence: float       # 0.0-1.0
    provenance: Provenance
    grade: str = "B"        # A | B | C
    heat: int = 50          # 0-100
    relations: list = field(default_factory=list)
    versions: list[VersionRef] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    custom_type: str = ""
    valid_from: int | None = None  # spec §10 / §5.9: knowledge start-of-validity (Unix ms)
    valid_to: int | None = None    # spec §10 / §5.9: knowledge end-of-validity (Unix ms)
