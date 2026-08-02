"""Write + read wiki pages as markdown with YAML frontmatter."""
from pathlib import Path

import yaml

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths
from ..core.types import PageType, WikiPage


_TYPE_TO_DIR: dict[PageType, str] = {
    PageType.SOURCE: "wiki_sources",
    PageType.ENTITY: "wiki_entities",
    PageType.CONCEPT: "wiki_concepts",
    PageType.SYNTHESIS: "wiki_synthesis",
    PageType.CLAIM: "wiki_claims",
    PageType.DECISION: "wiki_decisions",
}


class PageNotFoundError(Exception):
    pass


def page_path_for(paths: WikiPaths, type_: PageType, slug: str) -> Path:
    """Return canonical path for (type, slug)."""
    if type_ not in _TYPE_TO_DIR:
        raise ValueError(
            f"Stub pages should use page_path_for_stub instead of {type_}"
        )
    dir_prop = _TYPE_TO_DIR[type_]
    return getattr(paths, dir_prop) / f"{slug}.md"


def page_path_for_stub(paths: WikiPaths, slug: str) -> Path:
    return paths.wiki_stubs / f"{slug}.md"


def write_page(paths: WikiPaths, page: WikiPage) -> None:
    """Write page to disk via safe_write (respects AtomicContext).

    The page title lives in frontmatter only — we don't prepend a `# title`
    header so the body round-trips cleanly.
    """
    path = page_path_for(paths, page.type, page.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = page.to_frontmatter_dict()
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    content = f"---\n{fm_text}---\n\n{page.body}"
    safe_write(path, content)


def read_page(path: Path) -> WikiPage:
    """Parse markdown file → WikiPage. Raises PageNotFoundError if missing."""
    if not path.exists():
        raise PageNotFoundError(f"Page not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return WikiPage(id=path.stem, title=path.stem, type=PageType.SOURCE, body=text)
    end = text.find("\n---", 4)
    if end < 0:
        return WikiPage(id=path.stem, title=path.stem, type=PageType.SOURCE, body=text)
    fm_text = text[4:end]
    body = text[end + 5:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return WikiPage.from_dict(fm, body=body)
