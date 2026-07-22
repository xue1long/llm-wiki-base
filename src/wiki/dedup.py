"""LLM-driven duplicate-entity detection (A7, basic MVP)."""
import logging

from .paths import WikiPaths
from .page_writer import read_page


_logger = logging.getLogger(__name__)


def find_duplicates(paths: WikiPaths, provider=None) -> list[tuple[str, str]]:
    """Return list of (slug_a, slug_b) pairs to merge.

    MVP: returns empty list. Full LLM-driven detection deferred to v2.0.1.
    """
    entity_pages = [read_page(f) for f in paths.wiki_entities.glob("*.md")]
    if len(entity_pages) < 2:
        return []
    _logger.info(f"[dedup] {len(entity_pages)} entity pages; MVP returns []")
    return []
