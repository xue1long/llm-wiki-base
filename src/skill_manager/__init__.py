"""Domain types and safe inspection for managed agent Skills."""

from .api import apply_deployment, get_operation, import_artifact, list_artifacts, list_targets, plan_deployment
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
    DeploymentPlan,
    DeploymentTargetPlan,
    Operation,
)

__all__ = [
    "Artifact",
    "Deployment",
    "FileEntry",
    "PackageLimits",
    "PackageValidationError",
    "SourceInspection",
    "SourceSpec",
    "DeploymentPlan",
    "DeploymentTargetPlan",
    "Operation",
    "DEFAULT_PACKAGE_LIMITS",
    "build_artifact",
    "inspect_package",
    "inspect_source",
    "apply_deployment",
    "get_operation",
    "import_artifact",
    "list_artifacts",
    "list_targets",
    "plan_deployment",
]
