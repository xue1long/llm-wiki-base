# ruflo-kb/src/types.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

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


@dataclass(frozen=True)
class IngestSnapshot:
    instance_id: str
    source_identity: str
    source_version: str
    template_snapshot: dict[str, Any]
    pipeline_contract_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "source_identity": self.source_identity,
            "source_version": self.source_version,
            "template_snapshot": dict(self.template_snapshot),
            "pipeline_contract_version": self.pipeline_contract_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IngestSnapshot":
        return cls(
            instance_id=str(data["instance_id"]),
            source_identity=str(data["source_identity"]),
            source_version=str(data["source_version"]),
            template_snapshot=dict(data["template_snapshot"]),
            pipeline_contract_version=str(data["pipeline_contract_version"]),
        )

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
    ingest_snapshot: Optional[IngestSnapshot] = None

    def to_dict(self) -> dict[str, Any]:
        data = {"id": self.id, "source": self.source, "source_type": self.source_type.value,
                "status": self.status.value, "task_hash": self.task_hash,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "retry_count": self.retry_count, "error": self.error,
                "raw_path": self.raw_path, "note_path": self.note_path,
                "knowledge_path": self.knowledge_path, "project_id": self.project_id,
                "folder_context": self.folder_context, "batch_id": self.batch_id}
        if self.ingest_snapshot is not None:
            data["ingest_snapshot"] = self.ingest_snapshot.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeTask":
        snapshot_data = data.get("ingest_snapshot")
        return cls(
            id=data["id"], source=data["source"], source_type=SourceType(data["source_type"]),
            status=TaskStatus(data["status"]), task_hash=data["task_hash"],
            created_at=data["created_at"], updated_at=data["updated_at"],
            retry_count=data.get("retry_count", 0), error=data.get("error"),
            raw_path=data.get("raw_path"), note_path=data.get("note_path"),
            knowledge_path=data.get("knowledge_path"), project_id=data.get("project_id"),
            folder_context=data.get("folder_context"), batch_id=data.get("batch_id"),
            ingest_snapshot=IngestSnapshot.from_dict(snapshot_data) if snapshot_data else None,
        )

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
