"""Folder-aware ingest: pass folder_context to Analyzer (A2)."""
import logging
from pathlib import Path


_logger = logging.getLogger(__name__)


def collect_files(folder: Path) -> list[Path]:
    """Return list of files in folder (recursive)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [f for f in folder.rglob("*") if f.is_file()]


def folder_context_for(folder: Path, file: Path) -> str:
    """Build folder context hint like 'papers > energy' for LLM."""
    folder = Path(folder).resolve()
    file = Path(file).resolve()
    try:
        rel = file.relative_to(folder)
    except ValueError:
        return ""
    parts = list(rel.parts[:-1])  # exclude filename
    return " > ".join(parts)