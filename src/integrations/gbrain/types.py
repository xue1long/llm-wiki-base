"""Public project-scoped types for the optional GBrain integration."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


GBRAIN_SEARCH_MODES = ("conservative", "balanced", "tokenmax")


class SearchStatus(str, Enum):
    DISABLED = "disabled"
    QUEUED = "queued"
    SYNCING = "syncing"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SearchConfig:
    schema_version: int = 1
    enabled: bool = False
    source_id: str = ""
    source_name: str = ""
    source_path: str = "wiki"
    backend: str = "gbrain"
    consent_at: int = 0
    config_epoch: int = 1
    gbrain_mode: str = "balanced"
    result_limit: int = 20

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SearchConfig":
        mode = str(raw.get("gbrain_mode", "balanced"))
        if mode not in GBRAIN_SEARCH_MODES:
            mode = "balanced"
        try:
            result_limit = int(raw.get("result_limit", 20))
        except (TypeError, ValueError):
            result_limit = 20
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            enabled=bool(raw.get("enabled", False)),
            source_id=str(raw.get("source_id", "")),
            source_name=str(raw.get("source_name", "")),
            source_path=str(raw.get("source_path", "wiki")),
            backend=str(raw.get("backend", "gbrain")),
            consent_at=int(raw.get("consent_at", 0)),
            config_epoch=int(raw.get("config_epoch", 1)),
            gbrain_mode=mode,
            result_limit=max(1, min(result_limit, 50)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchState:
    status: SearchStatus = SearchStatus.DISABLED
    config_epoch: int = 1
    job_id: str = ""
    total_pages: int = 0
    synced_pages: int = 0
    failed_pages: int = 0
    embedding_coverage: float = 0.0
    path_mapping_coverage: float = 0.0
    manifest_hash: str = ""
    last_success_at: int = 0
    last_error_code: str = ""
    last_sync_duration_ms: int = 0

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SearchState":
        return cls(
            status=SearchStatus(str(raw.get("status", SearchStatus.DISABLED.value))),
            config_epoch=int(raw.get("config_epoch", 1)),
            job_id=str(raw.get("job_id", "")),
            total_pages=int(raw.get("total_pages", 0)),
            synced_pages=int(raw.get("synced_pages", 0)),
            failed_pages=int(raw.get("failed_pages", 0)),
            embedding_coverage=float(raw.get("embedding_coverage", 0.0)),
            path_mapping_coverage=float(raw.get("path_mapping_coverage", 0.0)),
            manifest_hash=str(raw.get("manifest_hash", "")),
            last_success_at=int(raw.get("last_success_at", 0)),
            last_error_code=str(raw.get("last_error_code", "")),
            last_sync_duration_ms=int(raw.get("last_sync_duration_ms", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class GBrainJob:
    id: str
    kind: str
    status: JobStatus
    config_epoch: int
    created_at: int
    updated_at: int
    error_code: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GBrainJob":
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            status=JobStatus(str(raw.get("status", JobStatus.QUEUED.value))),
            config_epoch=int(raw.get("config_epoch", 1)),
            created_at=int(raw.get("created_at", 0)),
            updated_at=int(raw.get("updated_at", 0)),
            error_code=str(raw.get("error_code", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class WikiSnapshotEntry:
    path: str
    slug: str
    page_type: str
    content_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "slug": self.slug,
            "page_type": self.page_type,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ReconcilePlan:
    added: list[str]
    updated: list[str]
    deleted: list[str]
    restored: list[str]
