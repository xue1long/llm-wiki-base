"""WikiPageAdapter — thin bridge over existing page_writer operations.

Used by MetadataStore to read/write WikiPage files.  Phase 5 introduces this
as a unified access point for what was previously direct page_writer calls
scattered across the codebase.
"""

from __future__ import annotations

from pathlib import Path

from ...lib.write_hooks import DELETE_SENTINEL, safe_write
from ...wiki.core.paths import WikiPaths
from ...wiki.core.types import PageType, WikiPage
from ...wiki.storage.page_writer import (
    PageNotFoundError,
    page_path_for,
    read_page,
    write_page,
)

# Directories to scan when looking up a page by ID (in priority order).
_SCAN_DIRS: list[str] = [
    "wiki_sources",
    "wiki_entities",
    "wiki_concepts",
    "wiki_synthesis",
    "wiki_claims",
    "wiki_decisions",
]


class WikiPageAdapter:
    """Thin adapter wrapping existing page_writer / WikiPage operations.

    Used by MetadataStore to read/write WikiPage files.  Phase 5 introduces
    this as a unified access point for what was previously direct page_writer
    calls scattered across the codebase.
    """

    def __init__(self, wiki_paths: WikiPaths) -> None:
        self._paths = wiki_paths

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _find_page_path(self, object_id: str) -> Path | None:
        """Find the .md file for *object_id* across all wiki subdirectories."""
        for dir_attr in _SCAN_DIRS:
            dir_path: Path = getattr(self._paths, dir_attr)
            candidate = dir_path / f"{object_id}.md"
            if candidate.exists():
                return candidate
        # Also check _stubs as a fallback.
        stub_candidate = self._paths.wiki_stubs / f"{object_id}.md"
        if stub_candidate.exists():
            return stub_candidate
        return None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def read_page(self, object_id: str) -> WikiPage | None:
        """Read a wiki page by its object ID.  Returns None when not found."""
        path = self._find_page_path(object_id)
        if path is None:
            return None
        try:
            return read_page(path)
        except PageNotFoundError:
            return None

    def write_page(self, page: WikiPage) -> None:
        """Write (create or overwrite) a wiki page."""
        write_page(self._paths, page)

    def delete_page(self, object_id: str) -> None:
        """Move the page to ``wiki/_archive/``."""
        path = self._find_page_path(object_id)
        if path is None:
            return
        archive_dir = self._paths.wiki / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_target = archive_dir / f"{object_id}.md"
        # Copy content to archive, then delete original via safe_write
        # so the operation respects AtomicContext.
        content = path.read_text(encoding="utf-8")
        safe_write(archive_target, content)
        safe_write(path, DELETE_SENTINEL)

    def list_pages(self) -> list[str]:
        """Return every page ID (stem) found under wiki/ subdirectories."""
        ids: list[str] = []
        for dir_attr in _SCAN_DIRS:
            dir_path: Path = getattr(self._paths, dir_attr)
            if dir_path.exists():
                for f in dir_path.glob("*.md"):
                    ids.append(f.stem)
        # Include stubs.
        if self._paths.wiki_stubs.exists():
            for f in self._paths.wiki_stubs.glob("*.md"):
                ids.append(f.stem)
        return ids
