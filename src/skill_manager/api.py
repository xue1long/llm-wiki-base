"""Public Skill Manager lifecycle API."""

from .agents import discover_targets
from .manager import apply_deployment, import_artifact, inspect_source, plan_deployment
from .storage import SkillManagerStorage
from .types import Artifact


def list_artifacts(*, storage: SkillManagerStorage | None = None) -> tuple[Artifact, ...]:
    storage = storage or SkillManagerStorage()
    root = storage.root / "artifacts"
    if not root.is_dir():
        return ()
    return tuple(storage.load_artifact(path.parent.name) for path in sorted(root.glob("*/artifact.json")))


def list_targets():
    return discover_targets()


def get_operation(operation_id: str, *, storage: SkillManagerStorage | None = None):
    return (storage or SkillManagerStorage()).load_operation(operation_id)

__all__ = [
    "SkillManagerStorage",
    "apply_deployment",
    "get_operation",
    "import_artifact",
    "inspect_source",
    "list_artifacts",
    "list_targets",
    "plan_deployment",
]
