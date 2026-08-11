"""Query API for page version snapshots — read-only, not on the write hot path."""
from __future__ import annotations

import json

from ..core.paths import WikiPaths


def get_version_history(paths: WikiPaths, page_id: str) -> list[dict]:
    """Return all saved versions for a page, oldest first."""
    version_dir = paths.index / "page_versions" / page_id
    if not version_dir.exists():
        return []
    results = []
    for f in sorted(version_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filename"] = f.name
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def get_version(paths: WikiPaths, page_id: str, version_filename: str) -> dict | None:
    """Read a single version snapshot by filename."""
    version_path = paths.index / "page_versions" / page_id / version_filename
    if not version_path.exists():
        return None
    try:
        data = json.loads(version_path.read_text(encoding="utf-8"))
        data["_filename"] = version_path.name
        return data
    except (json.JSONDecodeError, OSError):
        return None
