"""Safe, read-only inspection of local static Skill packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterable, Sequence

from ..project.paths import config_dir
from .agents import AgentTarget, DeploymentMarker, MANAGER_MARKER_NAME, discover_targets
from .sources import copy_local_skill
from .storage import manager_lock
from .types import (
    Artifact,
    Deployment,
    DeploymentPlan,
    DeploymentTargetPlan,
    FileEntry,
    PackageLimits,
    PackageValidationError,
    Operation,
    SourceInspection,
    SourceSpec,
)


DEFAULT_PACKAGE_LIMITS = PackageLimits()
_MARKER_NAME = ".ruflo-skill-manager.json"
_PLUGIN_NAME = "plugin.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def inspect_source(
    source: SourceSpec,
    *,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    forbidden_roots: Sequence[Path] | None = None,
    extra_paths: Iterable[Path] = (),
) -> SourceInspection:
    """Validate and hash a local static Skill without executing or copying it."""

    if source.kind != "local":
        raise PackageValidationError("UNSUPPORTED_SOURCE", "only local Skill sources are supported")
    root = _resolve_source(source.path)
    if forbidden_roots is None:
        forbidden_roots = (config_dir() / "skill-manager",)
    _reject_overlap(root, forbidden_roots)
    for candidate in extra_paths:
        _relative_path(root, Path(candidate))

    entries = _collect_files(root, limits)
    names = {entry.path.casefold() for entry in entries}
    if any(Path(entry.path).name.casefold() == _PLUGIN_NAME for entry in entries):
        raise PackageValidationError(
            "UNSUPPORTED_PLUGIN_TYPE", "plugin.json packages are not supported"
        )
    if _MARKER_NAME.casefold() in names:
        raise PackageValidationError(
            "MANAGER_MARKER_NOT_ALLOWED", "managed marker is owned by the manager"
        )
    if "skill.md" not in names:
        raise PackageValidationError("MISSING_SKILL_FILE", "package root must contain SKILL.md")

    content_hash = _content_hash(root, entries)
    name = _skill_name(root / "SKILL.md", root.name)
    artifact_id = f"skill-{content_hash}"
    return SourceInspection(
        source=source,
        package_type="skill",
        name=name,
        artifact_id=artifact_id,
        content_hash=content_hash,
        files=tuple(entries),
        total_bytes=sum(entry.size for entry in entries),
    )


def build_artifact(
    source: SourceSpec,
    *,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    forbidden_roots: Sequence[Path] | None = None,
) -> Artifact:
    """Turn a validated inspection into the immutable Task 1 domain value."""

    inspection = inspect_source(source, limits=limits, forbidden_roots=forbidden_roots)
    return Artifact(
        artifact_id=inspection.artifact_id,
        name=inspection.name,
        content_hash=inspection.content_hash,
        files=inspection.files,
        total_bytes=inspection.total_bytes,
        source=inspection.source,
    )


inspect_package = inspect_source


def import_artifact(
    source: SourceSpec,
    *,
    plan_hash: str,
    confirmation: str,
    storage=None,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
) -> Artifact:
    """Import a confirmed local source into an immutable Library snapshot."""

    if confirmation != "confirm":
        raise ValueError("explicit confirmation is required")
    if storage is None:
        from .storage import SkillManagerStorage

        storage = SkillManagerStorage()
    forbidden = [config_dir() / "skill-manager", storage.root]
    forbidden.extend(target.path for target in discover_targets())
    inspection = inspect_source(source, limits=limits, forbidden_roots=forbidden)
    if plan_hash != inspection.content_hash:
        raise ValueError("plan hash does not match source")
    artifact = Artifact(
        artifact_id=inspection.artifact_id,
        name=inspection.name,
        content_hash=inspection.content_hash,
        files=inspection.files,
        total_bytes=inspection.total_bytes,
        source=inspection.source,
    )
    artifact_root = storage.root / "artifacts" / artifact.artifact_id
    content = artifact_root / "content"
    if content.exists():
        current = inspect_source(SourceSpec(content), limits=limits, forbidden_roots=())
        if current.content_hash != artifact.content_hash:
            raise ValueError("stored Artifact content changed")
    else:
        staging = storage.root / "artifacts" / f".staging-{uuid.uuid4().hex}"
        try:
            copy_local_skill(source.path, staging / "content", inspection.files)
            copied = inspect_source(SourceSpec(staging / "content"), limits=limits, forbidden_roots=())
            if copied.content_hash != inspection.content_hash:
                raise ValueError("source changed during import")
            artifact_root.mkdir(parents=True, exist_ok=True)
            os.replace(staging / "content", content)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    storage.save_artifact(artifact)
    return artifact


def plan_deployment(
    artifact_id: str,
    target_ids: Sequence[str],
    *,
    storage=None,
) -> DeploymentPlan:
    """Preflight deployment and bind it to current target state."""

    if len(set(target_ids)) != len(target_ids):
        raise ValueError("duplicate deployment target")
    if storage is None:
        from .storage import SkillManagerStorage

        storage = SkillManagerStorage()
    artifact = storage.load_artifact(artifact_id)
    if not _SAFE_NAME.fullmatch(artifact.name):
        raise ValueError("Artifact name is not a safe single path segment")
    content = storage.root / "artifacts" / artifact.artifact_id / "content"
    current = inspect_source(SourceSpec(content), forbidden_roots=())
    if current.content_hash != artifact.content_hash or current.files != artifact.files:
        raise ValueError("stored Artifact content changed")
    targets = {target.id: target for target in discover_targets()}
    plans: list[DeploymentTargetPlan] = []
    for target_id in target_ids:
        target = targets.get(target_id)
        if target is None:
            raise ValueError(f"unknown deployment target: {target_id}")
        skill_path = target.path / artifact.name
        status, reason, fingerprint = _target_state(skill_path, artifact)
        plans.append(
            DeploymentTargetPlan(
                target_id=target.id,
                target_path=str(target.path),
                skill_path=str(skill_path),
                status=status,
                reason=reason,
                fingerprint=fingerprint,
            )
        )
    payload = {
        "artifact_id": artifact.artifact_id,
        "artifact_hash": artifact.content_hash,
        "targets": [vars(item) for item in plans],
    }
    plan_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DeploymentPlan(plan_hash, artifact.artifact_id, artifact.content_hash, tuple(plans))


def apply_deployment(
    plan: DeploymentPlan,
    *,
    plan_hash: str,
    confirmation: str,
    storage=None,
) -> Operation:
    """Apply a current, confirmed plan with compensation on later failures."""

    if plan_hash != plan.plan_hash:
        raise ValueError("plan hash does not match deployment plan")
    if confirmation != "confirm":
        raise ValueError("explicit confirmation is required")
    if storage is None:
        from .storage import SkillManagerStorage

        storage = SkillManagerStorage()
    with manager_lock(storage.root):
        return _apply_deployment_locked(plan, storage)


def _apply_deployment_locked(plan: DeploymentPlan, storage) -> Operation:
    """Apply a plan while the manager lock is held."""
    fresh = plan_deployment(
        plan.artifact_id, [target.target_id for target in plan.targets], storage=storage
    )
    operation_id = f"op-{uuid.uuid4().hex}"
    if fresh.plan_hash != plan.plan_hash:
        return _finish_operation(
            storage,
            Operation(operation_id, "conflict", plan.artifact_id, ({"reason": "plan_changed"},), "plan_changed"),
        )
    if any(target.status == "conflict" for target in fresh.targets):
        return _finish_operation(
            storage,
            Operation(
                operation_id,
                "conflict",
                plan.artifact_id,
                tuple({"target_id": target.target_id, "status": target.status, "reason": target.reason} for target in fresh.targets),
                "target_conflict",
            ),
        )
    artifact = storage.load_artifact(plan.artifact_id)
    _save_operation(storage, operation_id, "installing", plan.artifact_id)
    installed: list[tuple[AgentTarget, Path]] = []
    results: list[dict[str, str]] = []
    failure: str | None = None
    for target_plan in fresh.targets:
        target = AgentTarget(target_plan.target_id, Path(target_plan.target_path), exists=True)
        if target_plan.status == "no_op":
            results.append({"target_id": target.id, "status": "succeeded", "action": "no_op"})
            continue
        try:
            _install_one(artifact, target=target, storage=storage)
            installed.append((target, target.path / artifact.name))
            results.append({"target_id": target.id, "status": "succeeded", "action": "installed"})
        except Exception:
            failure = "install_failed"
            results.append({"target_id": target.id, "status": "failed", "error_code": failure})
            for remaining in fresh.targets[len(results):]:
                results.append({"target_id": remaining.target_id, "status": "not_attempted"})
            break
    if failure:
        rollback_failed = False
        for target, skill_path in reversed(installed):
            try:
                _remove_installed(skill_path, artifact)
                results.append({"target_id": target.id, "status": "rolled_back"})
            except Exception:
                rollback_failed = True
                results.append({"target_id": target.id, "status": "rollback_failed"})
        status = "partial_failure" if rollback_failed or len(fresh.targets) > 1 else "failed"
        return _finish_operation(storage, Operation(operation_id, status, plan.artifact_id, tuple(results), failure))
    saved_deployments: list[Deployment] = []
    try:
        for target_plan, result in zip(fresh.targets, results):
            if result.get("action") != "installed":
                continue
            deployment = Deployment(
                deployment_id=f"deployment-{uuid.uuid4().hex}",
                artifact_id=plan.artifact_id,
                target_id=target_plan.target_id,
                target_path=target_plan.skill_path,
                content_hash=plan.artifact_hash,
            )
            storage.save_deployment(deployment)
            saved_deployments.append(deployment)
    except Exception:
        rollback_failed = False
        for deployment in reversed(saved_deployments):
            try:
                storage.delete_deployment(deployment.deployment_id)
            except Exception:
                rollback_failed = True
                results.append({"target_id": deployment.target_id, "status": "record_rollback_failed"})
        for _, skill_path in reversed(installed):
            try:
                _remove_installed(skill_path, artifact)
                results.append({"target_id": skill_path.parent.name, "status": "rolled_back"})
            except Exception:
                rollback_failed = True
                results.append({"target_id": skill_path.parent.name, "status": "rollback_failed"})
        status = "partial_failure" if rollback_failed or len(installed) > 1 else "failed"
        return _finish_operation(storage, Operation(operation_id, status, plan.artifact_id, tuple(results), "deployment_record_failed"))
    return _finish_operation(storage, Operation(operation_id, "succeeded", plan.artifact_id, tuple(results)))


def _target_state(skill_path: Path, artifact: Artifact) -> tuple[str, str, str]:
    if skill_path.parent.is_symlink():
        return "conflict", "target root is a symlink", "symlink"
    if not skill_path.exists():
        return "ready", "", "missing"
    if not skill_path.is_dir():
        return "conflict", "target is not a directory", "invalid"
    marker_path = skill_path / MANAGER_MARKER_NAME
    if not marker_path.is_file():
        return "conflict", "target is unmanaged", "unmanaged"
    try:
        marker = DeploymentMarker.from_dict(json.loads(marker_path.read_text(encoding="utf-8")))
    except Exception:
        return "conflict", "deployment marker is invalid", "invalid"
    if marker.artifact_id != artifact.artifact_id or marker.content_hash != artifact.content_hash:
        return "conflict", "target is managed by another Artifact", marker.content_hash
    files, content_hash = _fingerprint(skill_path)
    if files != tuple(entry.path for entry in artifact.files) or content_hash != artifact.content_hash:
        return "conflict", "managed target content changed", content_hash
    if marker.files != files:
        return "conflict", "deployment marker file list changed", content_hash
    return "no_op", "already installed", content_hash


def _fingerprint(root: Path) -> tuple[tuple[str, ...], str]:
    entries: list[tuple[str, Path]] = []
    for current, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            path = Path(current) / filename
            relative = path.relative_to(root).as_posix()
            if relative == MANAGER_MARKER_NAME:
                continue
            entries.append((relative, path))
    digest = hashlib.sha256()
    names: list[str] = []
    for relative, path in sorted(entries):
        names.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return tuple(names), digest.hexdigest()


def _install_one(artifact: Artifact, *, target: AgentTarget, storage) -> None:
    target.path.mkdir(parents=True, exist_ok=True)
    skill_path = target.path / artifact.name
    staging = target.path / f".skill-manager-staging-{uuid.uuid4().hex}"
    try:
        copy_local_skill(storage.root / "artifacts" / artifact.artifact_id / "content", staging, artifact.files)
        files, content_hash = _fingerprint(staging)
        if files != tuple(entry.path for entry in artifact.files) or content_hash != artifact.content_hash:
            raise RuntimeError("staged Artifact content changed")
        marker = DeploymentMarker(
            artifact.artifact_id, artifact.content_hash, int(time.time() * 1000), "1", tuple(entry.path for entry in artifact.files)
        )
        (staging / MANAGER_MARKER_NAME).write_text(
            json.dumps(marker.to_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        if skill_path.exists():
            raise RuntimeError("target appeared during deployment")
        os.replace(staging, skill_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _remove_installed(skill_path: Path, artifact: Artifact) -> None:
    marker_path = skill_path / MANAGER_MARKER_NAME
    marker = DeploymentMarker.from_dict(json.loads(marker_path.read_text(encoding="utf-8")))
    if marker.artifact_id != artifact.artifact_id or marker.content_hash != artifact.content_hash:
        raise RuntimeError("installed target ownership changed")
    files, content_hash = _fingerprint(skill_path)
    if marker.files != files or content_hash != artifact.content_hash:
        raise RuntimeError("installed target content changed before rollback")
    shutil.rmtree(skill_path)


def _save_operation(storage, operation_id: str, status: str, artifact_id: str) -> None:
    storage.save_operation({"id": operation_id, "status": status, "artifact_id": artifact_id})


def _finish_operation(storage, operation: Operation) -> Operation:
    payload = {
        "id": operation.operation_id,
        "status": operation.status,
        "artifact_id": operation.artifact_id,
        "results": list(operation.results),
    }
    if operation.error_code:
        payload["error_code"] = operation.error_code
    storage.save_operation(payload)
    return operation


def _resolve_source(path: Path) -> Path:
    raw = Path(path)
    if raw.is_symlink():
        raise PackageValidationError("SYMLINK_NOT_ALLOWED", "source directory cannot be a symlink")
    try:
        root = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PackageValidationError("SOURCE_NOT_FOUND", "Skill source does not exist") from exc
    if not root.is_dir():
        raise PackageValidationError("SOURCE_NOT_DIRECTORY", "Skill source must be a directory")
    return root


def _reject_overlap(root: Path, forbidden_roots: Sequence[Path]) -> None:
    for forbidden in forbidden_roots:
        candidate = Path(forbidden).resolve()
        if root == candidate or root in candidate.parents or candidate in root.parents:
            raise PackageValidationError(
                "SOURCE_SELF_CONTAINED", "Skill source overlaps a manager-owned directory"
            )


def _relative_path(root: Path, path: Path) -> str:
    raw = Path(path)
    try:
        relative = raw.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise PackageValidationError("PATH_TRAVERSAL", "package path escapes source root") from exc
    if any(part in {"", ".", ".."} for part in raw.parts):
        raise PackageValidationError("PATH_TRAVERSAL", "package path contains traversal")
    return validate_package_path(relative.as_posix())


def validate_package_path(value: str) -> str:
    """Return a normalized relative package path or reject traversal."""

    if not isinstance(value, str) or not value or "\\" in value:
        raise PackageValidationError("PATH_TRAVERSAL", "package path is not a safe POSIX path")
    candidate = Path(value)
    if value.startswith("/") or candidate.is_absolute() or candidate.drive:
        raise PackageValidationError("PATH_TRAVERSAL", "package path must be relative")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise PackageValidationError("PATH_TRAVERSAL", "package path contains traversal")
    normalized = candidate.as_posix()
    if normalized != value:
        raise PackageValidationError("PATH_TRAVERSAL", "package path is not normalized")
    return normalized


def _collect_files(root: Path, limits: PackageLimits) -> list[FileEntry]:
    paths: list[tuple[str, Path]] = []
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for dirname in list(dirnames):
            directory = current_path / dirname
            if directory.is_symlink():
                raise PackageValidationError("SYMLINK_NOT_ALLOWED", "package cannot contain symlinks")
        dirnames.sort()
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                raise PackageValidationError("SYMLINK_NOT_ALLOWED", "package cannot contain symlinks")
            relative = _relative_path(root, path)
            if not path.is_file():
                raise PackageValidationError("UNSUPPORTED_ENTRY", "package contains a non-file entry")
            size = path.stat().st_size
            if size > limits.max_file_bytes:
                raise PackageValidationError("FILE_TOO_LARGE", "package file exceeds size limit")
            paths.append((relative, path))
            if len(paths) > limits.max_files:
                raise PackageValidationError("TOO_MANY_FILES", "package contains too many files")

    entries: list[FileEntry] = []
    total = 0
    for relative, path in sorted(paths):
        size = path.stat().st_size
        total += size
        if total > limits.max_total_bytes:
            raise PackageValidationError("PACKAGE_TOO_LARGE", "package exceeds total size limit")
        entries.append(FileEntry(relative, size, _file_hash(path)))
    return entries


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_hash(root: Path, entries: Sequence[FileEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\0")
        with (root / Path(entry.path)).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _skill_name(skill_file: Path, fallback: str) -> str:
    try:
        first_lines = skill_file.read_text(encoding="utf-8").splitlines()[:20]
    except UnicodeDecodeError as exc:
        raise PackageValidationError("INVALID_SKILL_FILE", "SKILL.md must be UTF-8 text") from exc
    for line in first_lines:
        if line.startswith("name:"):
            candidate = line.partition(":")[2].strip().strip("\"'")
            if candidate and _SAFE_NAME.fullmatch(candidate):
                return candidate
    if not _SAFE_NAME.fullmatch(fallback):
        raise PackageValidationError("INVALID_SKILL_NAME", "Skill directory name is not safe")
    return fallback
