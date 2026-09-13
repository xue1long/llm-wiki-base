"""Safe, read-only inspection of local static Skill packages."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Iterable, Sequence

from .types import (
    Artifact,
    FileEntry,
    PackageLimits,
    PackageValidationError,
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
    forbidden_roots: Sequence[Path] = (),
    extra_paths: Iterable[Path] = (),
) -> SourceInspection:
    """Validate and hash a local static Skill without executing or copying it."""

    if source.kind != "local":
        raise PackageValidationError("UNSUPPORTED_SOURCE", "only local Skill sources are supported")
    root = _resolve_source(source.path)
    _reject_overlap(root, forbidden_roots)
    for candidate in extra_paths:
        _relative_path(root, Path(candidate))

    entries = _collect_files(root, limits)
    names = {entry.path.casefold() for entry in entries}
    if _PLUGIN_NAME in names:
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
    forbidden_roots: Sequence[Path] = (),
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
    return relative.as_posix()


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
