"""Folder-aware ingest: pass folder_context to Analyzer (A2)."""
import logging
from pathlib import Path

from ...utils.path import safe_resolve

_logger = logging.getLogger(__name__)


def collect_files(folder: Path) -> list[Path]:
    """Return list of files in folder (recursive)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [f for f in folder.rglob("*") if f.is_file()]


def folder_context_for(folder: Path, file: Path) -> str:
    """Build folder context hint like 'papers > energy' for LLM."""
    folder = safe_resolve(folder)
    file = safe_resolve(file)
    try:
        rel = file.relative_to(folder)
    except ValueError:
        return ""
    parts = list(rel.parts[:-1])  # exclude filename
    return " > ".join(parts)