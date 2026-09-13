"""Domain types and safe inspection for managed agent Skills."""

from .manager import (
    DEFAULT_PACKAGE_LIMITS,
    build_artifact,
    inspect_package,
    inspect_source,
)
from .types import (
    Artifact,
    Deployment,
    FileEntry,
    PackageLimits,
    PackageValidationError,
    SourceSpec,
    SourceInspection,
)

__all__ = [
    "Artifact",
    "Deployment",
    "FileEntry",
    "PackageLimits",
    "PackageValidationError",
    "SourceInspection",
    "SourceSpec",
    "DEFAULT_PACKAGE_LIMITS",
    "build_artifact",
    "inspect_package",
    "inspect_source",
]
