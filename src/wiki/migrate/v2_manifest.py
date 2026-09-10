from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...lib.write_hooks import safe_write


ALLOWED_DISPOSITIONS = frozenset(
    {
        "migrated",
        "metadata-only",
        "archived",
        "skipped",
        "quarantined",
        "support-artifact",
        "pending",
    }
)


class ManifestError(ValueError):
    """Raised when a migration manifest is incomplete or unsafe."""


def _validate_relative_path(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ManifestError(f"invalid {field_name} path: {value}")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError(f"invalid {field_name} path: {value}")
    if path.as_posix() != value:
        raise ManifestError(f"invalid {field_name} path: {value}")


@dataclass(frozen=True)
class ManifestItem:
    source_path: str
    sha256: str
    size: int
    kind: str
    disposition: str
    target_path: str
    reason: str = ""


@dataclass(frozen=True)
class CheckpointItem:
    run_id: str
    source_path: str
    phase: str
    status: str


@dataclass
class MigrationManifest:
    run_id: str
    source_root: str
    project_root: str
    items: list[ManifestItem | dict[str, Any]]
    counts: dict[str, int] = field(default_factory=dict)
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        self.items = [
            item if isinstance(item, ManifestItem) else ManifestItem(**item)
            for item in self.items
        ]
        seen_sources: set[str] = set()
        seen_targets: set[str] = set()
        project_root = Path(self.project_root).resolve()

        for item in self.items:
            _validate_relative_path(item.source_path, "source")
            if item.source_path in seen_sources:
                raise ManifestError("duplicate source path")
            seen_sources.add(item.source_path)
            target = (project_root / item.target_path).resolve()
            if target != project_root and project_root not in target.parents:
                raise ManifestError(f"target outside project root: {item.target_path}")
            _validate_relative_path(item.target_path, "target")
            if item.target_path in seen_targets:
                raise ManifestError(f"duplicate target path: {item.target_path}")
            seen_targets.add(item.target_path)
            if item.disposition not in ALLOWED_DISPOSITIONS:
                raise ManifestError(f"invalid disposition: {item.disposition}")

        self.items.sort(key=lambda item: item.source_path)
        if not self.counts:
            self.counts = {
                "total": len(self.items),
                "raw": sum(item.source_path.startswith("10_raw/") for item in self.items),
                "wiki": sum(item.source_path.startswith("20_wiki/") for item in self.items),
            }
            for disposition in sorted(ALLOWED_DISPOSITIONS):
                self.counts[disposition] = sum(
                    item.disposition == disposition for item in self.items
                )
        else:
            self.counts = dict(self.counts)

        digest = self.digest()
        if self.manifest_hash and self.manifest_hash != digest:
            raise ManifestError("manifest hash mismatch")
        self.manifest_hash = digest

    def digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "source_root": self.source_root,
            "project_root": self.project_root,
            "items": [asdict(item) for item in self.items],
            "counts": self.counts,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_root": self.source_root,
            "project_root": self.project_root,
            "items": [asdict(item) for item in self.items],
            "counts": self.counts,
            "manifest_hash": self.manifest_hash,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify(relative: Path) -> tuple[str, str, str, str]:
    posix = relative.as_posix()
    name = relative.name
    if posix.startswith("10_raw/"):
        tail = relative.relative_to("10_raw")
        if name.endswith(".batch") or ".batch" in relative.parts:
            return "metadata", "metadata-only", f"raw/metadata/{name}", "batch metadata"
        if tail.parts and tail.parts[0] == "_archive":
            return "raw", "archived", (Path("raw/_archive") / Path(*tail.parts[1:])).as_posix(), "archive"
        if tail.parts and tail.parts[0] == "_skip":
            return "raw", "skipped", (Path("raw/_skip") / Path(*tail.parts[1:])).as_posix(), "skip"
        if tail.parts and tail.parts[0] == "_seed":
            return "seed", "migrated", (Path("raw/sources") / tail).as_posix(), "seed"
        return "raw", "migrated", (Path("raw/sources") / tail).as_posix(), "raw source"

    tail = relative.relative_to("20_wiki")
    if name in {"links.md", "overview.md"}:
        return "support", "support-artifact", (Path(".index/migration-support") / name).as_posix(), "support artifact"
    if name.startswith("invalid_"):
        return "wiki", "quarantined", (Path(".index/quarantine") / name).as_posix(), "invalid card"
    if "_to_recompile" in tail.parts:
        return "wiki", "pending", (Path("wiki/_pending") / name).as_posix(), "pending recompile"
    if tail.parts and tail.parts[0] == "entities":
        return "wiki", "migrated", (Path("wiki/entities") / name).as_posix(), "entity"
    return "wiki", "migrated", (Path("wiki/concepts") / name).as_posix(), "concept"


def build_manifest(source_root: Path, project_root: Path, run_id: str) -> MigrationManifest:
    source_root = Path(source_root).resolve()
    project_root = Path(project_root).resolve()
    if not source_root.is_dir():
        raise ManifestError(f"source root is not a directory: {source_root}")

    items: list[ManifestItem] = []
    for top in ("10_raw", "20_wiki"):
        base = source_root / top
        if not base.is_dir():
            continue
        paths = (
            path
            for path in base.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        for path in sorted(paths, key=lambda candidate: candidate.as_posix()):
            relative = path.relative_to(source_root)
            kind, disposition, target_path, reason = _classify(relative)
            items.append(
                ManifestItem(
                    source_path=relative.as_posix(),
                    sha256=_sha256(path),
                    size=path.stat().st_size,
                    kind=kind,
                    disposition=disposition,
                    target_path=target_path,
                    reason=reason,
                )
            )
    return MigrationManifest(str(run_id), str(source_root), str(project_root), items)


def save_manifest(project_root: Path, manifest: MigrationManifest) -> Path:
    path = (
        Path(project_root)
        / ".index"
        / "staging"
        / manifest.run_id
        / "migration-manifest.json"
    )
    safe_write(path, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return path


def load_manifest(path: Path) -> MigrationManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return MigrationManifest(**payload)
