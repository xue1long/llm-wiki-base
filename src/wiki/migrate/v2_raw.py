"""Safe raw-file mapping and copying for the v2 migration.

The v2 vault is an input-only source. This module only reads source files
and writes to an already-selected staging tree; it never mutates the vault.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable


class RawPathError(ValueError):
    """A source or target path is outside the migration contract."""


class RawCollisionError(FileExistsError):
    """A target already exists or multiple sources map to one target."""


class RawHashError(ValueError):
    """A source or copied file does not match its expected digest."""


_PLATFORM_DIRS = {
    "01_B站视频转录",
    "02_抖音视频笔记",
    "03_小红书收藏夹",
}


def _parts(path: Path) -> tuple[str, ...]:
    """Return portable path components without accepting traversal."""
    raw = str(path).replace("\\", "/")
    parts = tuple(part for part in raw.split("/") if part)
    if any(part in {".", ".."} for part in parts):
        raise RawPathError(f"path traversal is not allowed: {path}")
    return parts


def _source_tail(v2_path: Path) -> tuple[str, ...]:
    parts = _parts(v2_path)
    try:
        marker = parts.index("10_raw")
    except ValueError as exc:
        raise RawPathError(f"path is not under 10_raw: {v2_path}") from exc
    tail = parts[marker + 1 :]
    if not tail:
        raise RawPathError(f"raw path points at a directory: {v2_path}")
    return tail


def _target_root(root: Path) -> Path:
    return Path(root).resolve(strict=False)


def _inside(root: Path, target: Path) -> Path:
    target = target.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RawPathError(f"target escapes migration root: {target}") from exc
    return target


def map_raw_path(
    v2_path: Path,
    target_root: Path,
    *,
    add_platform_prefix: bool = False,
) -> Path:
    """Map one v2 ``10_raw`` path into the target layout."""
    tail = _source_tail(Path(v2_path))
    bucket = tail[0]
    remainder = tail[1:]
    root = _target_root(Path(target_root))

    if bucket == "_archive":
        target_parts = ("raw", "_archive", *remainder)
    elif bucket == "_skip":
        target_parts = ("raw", "_skip", *remainder)
    elif bucket == "_seed":
        target_parts = ("raw", "_seed", *remainder)
    elif tail[-1].lower().endswith(".batch"):
        target_parts = ("migration", "legacy", *tail)
    elif bucket in _PLATFORM_DIRS:
        filename = remainder[-1] if remainder else bucket
        if add_platform_prefix:
            filename = f"{bucket}__{filename}"
        target_parts = ("raw", "sources", *remainder[:-1], filename)
    else:
        target_parts = ("raw", "sources", *tail)

    return _inside(root, root.joinpath(*target_parts))


def collect_raw_files(v2_root: Path, *, include_skip: bool = False) -> list[Path]:
    """Collect raw files in deterministic order.

    ``v2_root`` may be the vault root or the ``10_raw`` directory itself.
    """
    root = Path(v2_root)
    raw_root = root / "10_raw" if (root / "10_raw").is_dir() else root
    if not raw_root.is_dir():
        return []
    files = []
    for path in raw_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(raw_root)
        if not include_skip and "_skip" in relative.parts:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(raw_root).as_posix())


def classify_raw(v2_path: Path) -> dict[str, str]:
    """Return the manifest classification for one raw source path."""
    parts = _source_tail(Path(v2_path))
    if parts[0] == "_archive":
        kind, disposition, reason = "archive", "archived", "raw archive"
    elif parts[0] == "_skip":
        kind, disposition, reason = "skip", "skipped", "raw skip directory"
    elif parts[0] == "_seed":
        kind, disposition, reason = "seed", "migrated", "seed source retained"
    elif parts[-1].lower().endswith(".batch"):
        kind, disposition, reason = "metadata", "metadata-only", "batch metadata"
    else:
        kind, disposition, reason = "source", "migrated", "raw source"
    return {
        "source_path": "/".join(("10_raw", *parts)),
        "kind": kind,
        "disposition": disposition,
        "reason": reason,
    }


def detect_collisions(
    files: Iterable[Path],
    target_root: Path,
    *,
    add_platform_prefix: bool = False,
) -> list[dict[str, object]]:
    """Group source files whose mapped target paths are identical."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for source in files:
        target = map_raw_path(
            Path(source), target_root, add_platform_prefix=add_platform_prefix
        )
        grouped[str(target)].append(str(source).replace("\\", "/"))
    return [
        {"target_path": target, "source_paths": sorted(sources)}
        for target, sources in sorted(grouped.items())
        if len(sources) > 1
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_raw_file(
    source: Path,
    target: Path,
    *,
    staging_root: Path,
    expected_sha256: str | None = None,
) -> Path:
    """Copy one file into staging without overwriting an existing target."""
    source = Path(source)
    if not source.is_file():
        raise RawPathError(f"source is not a file: {source}")
    staging = Path(staging_root).resolve(strict=False)
    target = Path(target)
    if not target.is_absolute():
        target = staging / target
    target = _inside(staging, target)
    if target == staging:
        raise RawPathError("target must be a file below staging_root")
    if target.exists():
        raise RawCollisionError(f"target already exists: {target}")

    source_hash = sha256_file(source)
    if expected_sha256 is not None and source_hash.lower() != expected_sha256.lower():
        raise RawHashError(
            f"source hash mismatch: expected {expected_sha256}, got {source_hash}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
                for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            try:
                target.unlink()
            except OSError:
                pass
            raise
    except FileExistsError as exc:
        raise RawCollisionError(f"target already exists: {target}") from exc

    copied_hash = sha256_file(target)
    if copied_hash != source_hash:
        target.unlink(missing_ok=True)
        raise RawHashError(
            f"copied hash mismatch: expected {source_hash}, got {copied_hash}"
        )
    return target
