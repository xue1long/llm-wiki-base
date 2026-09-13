"""Agent target discovery and manager-owned deployment markers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANAGER_MARKER_NAME = ".ruflo-skill-manager.json"


class AgentTargetError(ValueError):
    """Stable error for an unsafe or unavailable Agent target."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AgentTarget:
    id: str
    path: Path
    scope: str = "user"
    exists: bool = False


@dataclass(frozen=True)
class DeploymentMarker:
    artifact_id: str
    content_hash: str
    installed_at: int
    manager_version: str
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "installed_at": self.installed_at,
            "manager_version": self.manager_version,
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeploymentMarker":
        try:
            files = tuple(str(item) for item in payload["files"])
            return cls(
                artifact_id=str(payload["artifact_id"]),
                content_hash=str(payload["content_hash"]),
                installed_at=int(payload["installed_at"]),
                manager_version=str(payload["manager_version"]),
                files=files,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentTargetError("MARKER_CORRUPT", "invalid deployment marker") from exc


def discover_targets() -> tuple[AgentTarget, ...]:
    home = Path.home()
    return (
        AgentTarget("codex", home / ".codex" / "skills", exists=(home / ".codex" / "skills").is_dir()),
        AgentTarget(
            "claude_code",
            home / ".claude" / "skills",
            exists=(home / ".claude" / "skills").is_dir(),
        ),
    )


def resolve_custom_target(target_id: str, path: Path, *, allowed_root: Path) -> AgentTarget:
    raw = Path(path)
    if raw.is_symlink():
        raise AgentTargetError("TARGET_SYMLINK", "custom target cannot be a symlink")
    allowed = Path(allowed_root).resolve(strict=False)
    resolved = raw.resolve(strict=False)
    if resolved != allowed and allowed not in resolved.parents:
        raise AgentTargetError("TARGET_OUTSIDE_ALLOWED_ROOT", "custom target escapes allowed root")
    if not resolved.is_dir():
        raise AgentTargetError("TARGET_NOT_FOUND", "custom target must already exist")
    return AgentTarget(target_id, resolved, scope="custom", exists=True)
