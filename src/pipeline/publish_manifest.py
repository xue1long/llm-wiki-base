"""Task-scoped publish marker and rollback boundary."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .quarantine import quarantine_task
from ..wiki.storage.page_writer import write_page


class CommitError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommitResult:
    status: str
    task_id: str
    marker: Path | None = None


def mark_published(paths, task_id: str, bundle_hash: str = "") -> Path:
    """Write the visibility marker only after the existing commit succeeds."""
    target = Path(paths.index) / "staging" / task_id
    target.mkdir(parents=True, exist_ok=True)
    marker = target / "publish.marker"
    marker.write_text(json.dumps({"task_id": task_id, "bundle_hash": bundle_hash}), encoding="utf-8")
    return marker


def is_manual_conflict(existing_page, expected_version) -> bool:
    if expected_version is None:
        return False
    path = getattr(existing_page, "path", existing_page)
    path = Path(path)
    if not path.exists():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() != expected_version


def commit_bundle(bundle, context) -> CommitResult:
    paths = getattr(context, "paths", None)
    if paths is None:
        raise CommitError("missing project paths")
    task_id = str(getattr(context, "task_id", bundle.task_id))
    staging = Path(paths.index) / "staging" / task_id
    staging.mkdir(parents=True, exist_ok=True)
    manifest = staging / "manifest.json"
    manifest.write_text(json.dumps({"task_id": task_id, "bundle_hash": bundle.bundle_hash}, indent=2), encoding="utf-8")
    targets = []
    for page in bundle.pages:
        path = _page_path(paths, page)
        targets.append((path, path.read_bytes() if path.exists() else None))
    expected_versions = getattr(context, "expected_versions", {}) or {}
    for page, (path, _) in zip(bundle.pages, targets):
        expected = expected_versions.get(getattr(page, "id", ""), expected_versions.get(str(path)))
        if expected is not None and is_manual_conflict(path, expected):
            quarantine_task(context, reason_code="manual_version_conflict", errors=[str(path)], artifacts={"bundle_hash": bundle.bundle_hash})
            return CommitResult("quarantined", task_id)
    writer = getattr(context, "writer", write_page)
    try:
        for page in bundle.pages:
            writer(paths, page)
    except Exception as exc:
        for path, previous in targets:
            if previous is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous)
        quarantine_task(context, reason_code="commit_failed", errors=[str(exc)], artifacts={"bundle_hash": bundle.bundle_hash})
        raise CommitError(str(exc)) from exc
    marker = mark_published(paths, task_id, bundle.bundle_hash)
    return CommitResult("published", task_id, marker)


def _page_path(paths, page) -> Path:
    from ..wiki.storage.page_writer import page_path_for, page_path_for_stub
    if getattr(page, "processing_depth", "") == "stub":
        return page_path_for_stub(paths, page.id)
    return page_path_for(paths, page.type, page.id)


__all__ = ["CommitError", "CommitResult", "commit_bundle", "is_manual_conflict", "mark_published"]
