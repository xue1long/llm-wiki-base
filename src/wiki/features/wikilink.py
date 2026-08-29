"""Wikilink [[name|alias]] parsing, resolving, and stub auto-creation."""
from __future__ import annotations
import re
from pathlib import Path

import yaml

from ..storage.ensure import ensure_knowledge_base
from ...lib.write_hooks import safe_write
from ..core.paths import WikiPaths
from ..core.types import PageType, WikiPage


# [[target]] or [[target|alias]] — group 1 = target, group 2 = optional alias.
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Return the list of wikilink targets in ``text`` (in order)."""
    return [m.group(1).strip() for m in WIKILINK_PATTERN.finditer(text)]


def resolve_wikilink(project_root: Path, target: str) -> bool:
    """Return True if a wiki page with id == ``target`` exists in the project.

    Resolution chain:
      1. Exact filename match in any of the typed wiki directories.
      2. Fallback through ``SlugAliasRegistry`` — if ``target`` is a
         registered alias of a canonical slug AND that canonical page
         exists on disk, return True. Closes the LLM slug-drift gap
         observed on novel-wiki 2026-07-26 (e.g. ``qi-dai-gan`` →
         ``qi-dai-gan-chuangzuo``).
    """
    if not project_root.exists():
        return False
    paths = WikiPaths(project_root)
    if "/" in target or "\\" in target:
        normalized = target.replace("\\", "/").lstrip("/")
        return (paths.wiki / f"{normalized}.md").exists()
    type_dirs = (
        "wiki_sources", "wiki_entities", "wiki_concepts",
        "wiki_synthesis", "wiki_stubs",
    )
    # Step 1: exact match (existing behavior).
    for dir_prop in type_dirs:
        d = getattr(paths, dir_prop)
        if (d / f"{target}.md").exists():
            return True
    # Step 2: alias chain.  Lazy-import to avoid a heavy module load
    # when no aliases exist (the common case).
    try:
        from .slug_aliases import SlugAliasRegistry
    except ModuleNotFoundError:
        return False  # module absent — aliases not available, not an error
    try:
        reg = SlugAliasRegistry(project_root)
        canonical = reg.get_canonical(target)
    except Exception as e:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning("[wikilink] SlugAliasRegistry lookup failed for %r: %s", target, e)
        return False
    if not canonical:
        return False
    # Step 2b: verify the canonical slug actually resolves to a file.
    for dir_prop in type_dirs:
        d = getattr(paths, dir_prop)
        if (d / f"{canonical}.md").exists():
            return True
    return False


def create_stub_if_missing(project_root: Path, target: str) -> Path | None:
    """If no page exists for ``target``, write a stub at ``wiki/_stubs/<target>.md``.

    Stubs go to ``_stubs/`` regardless of the eventual ``PageType`` — the writer
    for a normal typed page routes by type, but a stub has no committed type yet,
    so we bypass ``write_page`` and write the markdown directly.

    Returns the path to the created stub, or None if a real page already exists.

    .. deprecated:: 1.3 (plan 1.3-6 / O1)
       Automatic stub creation is removed — unresolved references now go to the
       ``.index/knowledge_gaps.json`` ledger (``KnowledgeGapStore``) instead of
       creating stub pages.  Kept only for backward-compatible callers/tests.
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
    safe_write(path, content)
    return path
