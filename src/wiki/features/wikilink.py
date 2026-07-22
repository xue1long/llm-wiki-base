"""Wikilink [[name|alias]] parsing, resolving, and stub auto-creation."""
from __future__ import annotations
import re
from pathlib import Path

import yaml

from ..storage.ensure import ensure_knowledge_base
from ..core.paths import WikiPaths
from ..core.types import PageType, WikiPage


# [[target]] or [[target|alias]] — group 1 = target, group 2 = optional alias.
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Return the list of wikilink targets in ``text`` (in order)."""
    return [m.group(1).strip() for m in WIKILINK_PATTERN.finditer(text)]


def resolve_wikilink(project_root: Path, target: str) -> bool:
    """Return True if a wiki page with id == ``target`` exists in the project."""
    if not project_root.exists():
        return False
    paths = WikiPaths(project_root)
    for dir_prop in (
        "wiki_sources", "wiki_entities", "wiki_concepts", "wiki_synthesis", "wiki_stubs",
    ):
        d = getattr(paths, dir_prop)
        if (d / f"{target}.md").exists():
            return True
    return False


def create_stub_if_missing(project_root: Path, target: str) -> Path | None:
    """If no page exists for ``target``, write a stub at ``wiki/_stubs/<target>.md``.

    Stubs go to ``_stubs/`` regardless of the eventual ``PageType`` — the writer
    for a normal typed page routes by type, but a stub has no committed type yet,
    so we bypass ``write_page`` and write the markdown directly.

    Returns the path to the created stub, or None if a real page already exists.
    """
    if resolve_wikilink(project_root, target):
        return None
    paths = ensure_knowledge_base(project_root)
    page = WikiPage(
        id=target,
        title=target.replace("-", " ").title(),
        type=PageType.CONCEPT,
        sources=[],
        body="",
    )
    fm_text = yaml.dump(
        page.to_frontmatter_dict(),
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    content = f"---\n{fm_text}---\n\n{page.body}"
    path = paths.wiki_stubs / f"{target}.md"
    path.write_text(content, encoding="utf-8")
    return path
