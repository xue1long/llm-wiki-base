# ruflo-kb/src/events/events.py
from dataclasses import dataclass
from typing import Optional
from ..types import TaskStatus, SourceType

class EventName:
    TASK_CREATED = "task:created"
    TASK_STATUS_CHANGED = "task:status:changed"
    TASK_DEAD_LETTER = "task:dead_letter"
    COLLECTOR_DONE = "collector:done"
    PROCESSOR_DONE = "processor:done"
    LIBRARIAN_DONE = "librarian:done"
    LIBRARIAN_MERGED = "librarian:merged"
    SEARCHER_QUERY = "searcher:query"
    SEARCHER_RESULT = "searcher:result"

@dataclass
class TaskCreatedPayload:
    task_id: str
    source: str
    source_type: SourceType
    task_hash: str
    status: str = "pending"
    # Audit I5: optional project_id so the collector/ingest chain can
    # resolve the correct WikiPaths rather than the CWD-relative default.
    project_id: str | None = None

@dataclass
class TaskStatusChangedPayload:
    task_id: str
    from_status: TaskStatus
    to_status: TaskStatus
    error: Optional[str] = None

@dataclass
class TaskDeadLetterPayload:
    task_id: str
    retry_count: int
    error: Optional[str] = None

@dataclass
class CollectorDonePayload:
    task_id: str
    raw_path: str
    content: str
    # Original source path as it was supplied by the ingest caller —
    # typically a project-relative ``raw/sources/<file>`` for files or a
    # URL string for web sources. Carried through for log/audit and
    # tests; the pipeline does NOT modify the source artefact (the
    # file stays at its original location after ingest).
    source: str | None = None

@dataclass
class ProcessorDonePayload:
    task_id: str
    note_path: str
    quality_score: float
    ad_ratio: float
    text_density: float
    fluency_score: float

@dataclass
class LibrarianDonePayload:
    task_id: str
    knowledge_path: str
    chunk_count: int

@dataclass
class LibrarianMergedPayload:
    task_id: str
    existing_path: str
    merged_content: str

@dataclass
class SearcherQueryPayload:
    query: str
    mode: str = "hybrid"

@dataclass
class SearcherResultPayload:
    query: str
    results: list[dict]
