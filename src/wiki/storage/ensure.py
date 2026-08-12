"""Ensure the knowledge-base directory tree exists."""
from pathlib import Path

from ..core.paths import WikiPaths
from ..schema_registry import SchemaRegistry


def ensure_knowledge_base(
    root: Path | str, registry: SchemaRegistry | None = None,
) -> WikiPaths:
    """Create wiki/, raw/, .index/, .llm-wiki/ + subdirectories if missing.

    When *registry* is given, also creates a ``wiki/<dir>/`` per custom
    type declared in schema.md.

    Returns the WikiPaths for the project root so callers can keep using the
    layout without re-resolving.
    """
    paths = WikiPaths(Path(root))
    for d in [
        paths.wiki_sources,
        paths.wiki_entities,
        paths.wiki_concepts,
        paths.wiki_synthesis,
        paths.wiki_claims,
        paths.wiki_decisions,
        paths.wiki_stubs,
        paths.raw_sources,
        paths.index,
        paths.llm_wiki,
    ]:
        d.mkdir(parents=True, exist_ok=True)
    if registry is not None:
        for name in registry.all_custom_type_names():
            paths.get_custom_dir(registry.get_directory(name)).mkdir(
                parents=True, exist_ok=True,
            )
    return paths
