"""Validate wiki page types live in correct subdirs."""
from .ensure import ensure_knowledge_base
from .page_writer import read_page
from .paths import WikiPaths
from .types import PageType


_TYPE_TO_DIR = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
}


def validate_schema_routing(paths: WikiPaths) -> list[str]:
    """Return list of page IDs in wrong subdirs."""
    ensure_knowledge_base(paths.root)
    misrouted = []
    for page_type, dir_prop in _TYPE_TO_DIR.items():
        sub = getattr(paths, dir_prop)
        for md_file in sub.glob("*.md"):
            page = read_page(md_file)
            if page.type != page_type:
                misrouted.append(
                    f"{page.id} (in {dir_prop}, type={page.type.value})"
                )
    return misrouted