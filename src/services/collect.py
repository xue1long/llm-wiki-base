"""Synchronous source collection service."""
from __future__ import annotations

from pathlib import Path

from ..collector.collector import Collector
from ..lib.project import resolve_project


_COLLECTABLE_EXTS = {
    ".pdf", ".docx", ".xlsx", ".html", ".htm", ".txt", ".md", ".markdown",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif",
}


class CollectPathError(ValueError):
    """Uploaded file extension is not supported."""


async def collect_file(
    project_id: str,
    filename: str,
    content: bytes,
    *,
    llm_provider=None,
) -> dict:
    """Convert an uploaded file and write it to ``raw/sources``."""
    _, paths = resolve_project(project_id, by_id_only=True)
    ext = Path(filename).suffix.lower()
    if ext not in _COLLECTABLE_EXTS and not _is_url(filename):
        raise CollectPathError(
            f"Unsupported file type: {ext!r}. Supported: {sorted(_COLLECTABLE_EXTS)}"
        )

    result = await Collector(
        project_root=paths.root, llm_provider=llm_provider
    ).collect(filename, content=content)
    return {
        "status": "ok",
        "raw_path": result.original_path,
        "title": result.title,
        "source_type": result.source_type,
        "metadata": result.metadata,
    }


async def collect_url(project_id: str, url: str, *, llm_provider=None) -> dict:
    """Fetch, convert, and write a URL source to ``raw/sources``."""
    _, paths = resolve_project(project_id, by_id_only=True)
    result = await Collector(
        project_root=paths.root, llm_provider=llm_provider
    ).collect(url)
    return {
        "status": "ok",
        "raw_path": result.original_path,
        "title": result.title,
        "source_type": result.source_type,
        "metadata": result.metadata,
    }


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))
