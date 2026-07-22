"""Maintain wiki/index.md as a flat catalog of all pages."""
from typing import Iterable

from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths
from ..core.types import PageType


INDEX_HEADER = "# Wiki Index\n\n"


def _format_entry(slug: str, type: PageType, title: str) -> str:
    return f"- **{slug}** ({type.value}) — {title}\n"


def append_to_index(
    paths: WikiPaths,
    entries: Iterable[tuple[str, PageType, str]],
) -> None:
    """Append entries to wiki/index.md. Idempotent (dedup by slug)."""
    existing_slugs = set()
    if paths.llm_wiki_index.exists():
        for line in paths.llm_wiki_index.read_text(encoding="utf-8").split("\n"):
            if line.startswith("- **"):
                # Extract slug from "**slug**"
                try:
                    slug = line.split("**")[1]
                    existing_slugs.add(slug)
                except IndexError:
                    pass

    new_lines = []
    for slug, type, title in entries:
        if slug in existing_slugs:
            continue
        new_lines.append(_format_entry(slug, type, title))
        existing_slugs.add(slug)

    if not new_lines:
        return

    # Append to file
    if not paths.llm_wiki_index.exists():
        content = INDEX_HEADER
    else:
        content = paths.llm_wiki_index.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
    content += "".join(new_lines)
    safe_write(paths.llm_wiki_index, content)


def read_index(paths: WikiPaths) -> list[tuple[str, PageType, str]]:
    """Parse wiki/index.md → list of (slug, type, title)."""
    if not paths.llm_wiki_index.exists():
        return []
    out = []
    for line in paths.llm_wiki_index.read_text(encoding="utf-8").split("\n"):
        if not line.startswith("- **"):
            continue
        # Format: - **slug** (type) — title
        try:
            slug_part, rest = line.split("**", 2)[1], line.split("**", 2)[2]
            type_str = rest.split("(")[1].split(")")[0]
            title = rest.split("—", 1)[1].strip()
            out.append((slug_part, PageType(type_str), title))
        except (IndexError, ValueError):
            continue
    return out