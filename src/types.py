# ruflo-kb/src/types.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DEAD_LETTER = "dead_letter"

class SourceType(str, Enum):
    URL = "url"
    FILE = "file"

@dataclass
class KnowledgeTask:
    id: str
    source: str
    source_type: SourceType
    status: TaskStatus
    task_hash: str
    created_at: int
    updated_at: int
    retry_count: int = 0
    error: Optional[str] = None
    raw_path: Optional[str] = None
    note_path: Optional[str] = None
    knowledge_path: Optional[str] = None
    # Audit I5: optional project_id so the collector/pipeline chain can
    # resolve the correct project's WikiPaths rather than the CWD-relative
    # default. Persisted on disk so it survives queue reloads.
    project_id: Optional[str] = None
    # Phase 2.2: folder_context for idempotency + batch_id for tracking.
    folder_context: Optional[str] = None
    batch_id: Optional[str] = None

@dataclass
class ProcessedNote:
    title: str
    summary: str
    tags: list[str]
    content: str
    source: str
    processed_at: int
    quality_score: float
    ad_ratio: float
    text_density: float
    fluency_score: float
    metadata: dict = field(default_factory=dict)

@dataclass
class VectorChunk:
    id: str
    task_id: str
    content: str
    embedding: list[float]
    path: str
    updated_at: int

@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    endpoint: Optional[str] = None
    max_context_size: int = 4096
