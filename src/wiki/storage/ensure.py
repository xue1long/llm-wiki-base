"""Ensure the knowledge-base directory tree exists."""
from pathlib import Path

from ..core.paths import WikiPaths


def ensure_knowledge_base(root: Path | str) -> WikiPaths:
    """Create wiki/, raw/, .index/, .llm-wiki/ + subdirectories if missing.

    Returns the WikiPaths for the project root so callers can keep using the
    layout without re-resolving.
    """
    paths = WikiPaths(Path(root))
    for d in [
        paths.wiki_sources,
        paths.wiki_entities,
        paths.wiki_concepts,
        paths.wiki_synthesis,
        paths.wiki_stubs,
        paths.raw_sources,
        paths.index,
        paths.llm_wiki,
    ]:
        d.mkdir(parents=True, exist_ok=True)
    return paths
