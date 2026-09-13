"""Small, immutable domain vocabulary for the Skill manager."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    """A source locator; Task 1 supports local directories only."""

    path: Path
    kind: str = "local"

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class PackageLimits:
    """Safety limits applied while inspecting a package."""

    max_file_bytes: int = 1024 * 1024
    max_total_bytes: int = 5 * 1024 * 1024
    max_files: int = 256


@dataclass(frozen=True)
class FileEntry:
    """Deterministic metadata for one package file."""

    path: str
    size: int
    content_hash: str


@dataclass(frozen=True)
class SourceInspection:
    """Validated package metadata, without writing to the Library."""

    source: SourceSpec
    package_type: str
    name: str
    artifact_id: str
    content_hash: str
    files: tuple[FileEntry, ...]
    total_bytes: int


@dataclass(frozen=True)
class Artifact:
    """An immutable validated Skill snapshot identity."""

    artifact_id: str
    name: str
    content_hash: str
    files: tuple[FileEntry, ...]
    total_bytes: int
    source: SourceSpec


@dataclass(frozen=True)
class Deployment:
    """A record assigning one Artifact to one concrete Agent target."""

    deployment_id: str
    artifact_id: str
    target_id: str
    target_path: str
    content_hash: str


@dataclass(frozen=True)
class DeploymentTargetPlan:
    """Preflight result for one Agent target."""

    target_id: str
    target_path: str
    skill_path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class DeploymentPlan:
    """Hash-bound deployment preview."""

    plan_hash: str
    artifact_id: str
    artifact_hash: str
    targets: tuple[DeploymentTargetPlan, ...]


@dataclass(frozen=True)
class Operation:
    """Synchronous operation result persisted for later polling."""

    operation_id: str
    status: str
    artifact_id: str
    results: tuple[dict[str, Any], ...] = ()
    error_code: str | None = None


class PackageValidationError(ValueError):
    """Stable, caller-visible rejection for an unsafe or unsupported package."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)

    @property
    def error_code(self) -> str:
        return self.code
