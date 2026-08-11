"""Per-project ingest settings — auto-archive toggle.

This is the configuration landing spot for T5 (guarded auto-archive). It
reads a small JSON file under ``<root>/.llm-wiki/ingest_settings.json``
(project-local settings that survive export) rather than extending the
global project registry's data model. Missing file / missing key / malformed
JSON all fall back to ``{"auto_archive": False}`` so old projects and
corrupt files never break ingestion.

The module is import-side-effect free and never writes — the toggle is
turned on by an external writer (CLI/UI in a later phase). Default is OFF,
which keeps ingestion behaviour identical to before this change.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..wiki.core.paths import WikiPaths

_DEFAULTS: dict = {"auto_archive": False}


def load_ingest_settings(paths: WikiPaths) -> dict:
    """Return the ingest settings dict for the project.

    Always returns a dict. On any failure (file missing, unreadable,
    invalid JSON, non-dict content) returns the safe default
    ``{"auto_archive": False}`` so callers can rely on ``.get(...)``.
    """
    cfg_path: Path = paths.llm_wiki / "ingest_settings.json"
    if not cfg_path.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt or unreadable settings must never break ingestion.
        return dict(_DEFAULTS)
    if not isinstance(data, dict):
        return dict(_DEFAULTS)
    # Merge onto defaults so missing keys still resolve safely.
    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def is_auto_archive_enabled(paths: WikiPaths) -> bool:
    """True only when the project explicitly opts in via settings."""
    return bool(load_ingest_settings(paths).get("auto_archive", False))
