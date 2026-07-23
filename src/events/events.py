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

@dataclass
class TaskStatusChangedPayload:
    task_id: str
    from_status: TaskStatus
    to_status: TaskStatus
    error: Optional[str] = None

@dataclass
class CollectorDonePayload:
    task_id: str
    raw_path: str
    content: str

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
