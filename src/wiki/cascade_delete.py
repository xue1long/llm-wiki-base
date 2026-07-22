"""cascade_delete — remove a source page and clean up all dependents.

When a source is deleted, any entity/concept/synthesis page that references
any of its source paths must either be updated (drop the reference) or
deleted entirely (if it has no other sources). The wiki index is also
rebuilt without the source slug.

All operations run inside atomic_pipeline_op() so partial failure leaves
the wiki unchanged.
"""
import logging
import os
import time

from .ensure import ensure_knowledge_base
from .indexer import append_to_index, read_index
from .page_writer import read_page, write_page, page_path_for
from .paths import WikiPaths
from .types import WikiPage

_logger = logging.getLogger(__name__)


def cascade_delete(paths: WikiPaths, source_id: str) -> dict:
    """Delete a source page and cascade to all pages that reference it.

    Behavior:
        - Raises FileNotFoundError if the source page file is missing.
        - Reads the source page to learn its source paths.
        - For each other page (entity/concept/synthesis) whose sources[]
          contains any of those paths (or whose sources[] contains the
          source_id as a substring):
            * If sources[] becomes empty after removal → page is deleted.
            * Otherwise → page is rewritten with reduced sources[] and
              a bumped updated_at.
        - Source page file is deleted.
        - wiki/index.md is rebuilt without the source slug.
        - Caller should wrap this in atomic_pipeline_op() so all writes
          batch as one commit.

    Returns:
        {"deleted_source": bool, "updated_pages": list[str],
         "deleted_pages": list[str]}
    """
    ensure_knowledge_base(paths.root)
    source_path = paths.wiki_sources / f"{source_id}.md"
    if not source_path.exists():
        raise FileNotFoundError(f"Source page not found: {source_id}")

    # Read the source page itself to learn which raw paths it represents.
    # Other pages reference the source via these same path strings (and/or
    # via the source_id substring for future prefix-style identifiers).
    source_page = read_page(source_path)
    source_keys = set(source_page.sources) | {source_id}

    # Find affected pages across all wiki subdirectories
    affected_pages: list[WikiPage] = []
    for sub in [
        paths.wiki_sources,
        paths.wiki_entities,
        paths.wiki_concepts,
        paths.wiki_synthesis,
    ]:
        for md_file in sub.glob("*.md"):
            page = read_page(md_file)
            if any(k in s for s in page.sources for k in source_keys):
                affected_pages.append(page)

    # Update or delete each affected page
    deleted_pages: list[str] = []
    updated_pages: list[str] = []
    for page in affected_pages:
        if page.id == source_id:
            # The source page itself is removed by os.unlink below
            continue
        new_sources = [
            s for s in page.sources
            if not any(k in s for k in source_keys)
        ]
        if not new_sources:
            page_file = page_path_for(paths, page.type, page.id)
            if page_file.exists():
                os.unlink(page_file)
            deleted_pages.append(page.id)
        else:
            page.sources = new_sources
            page.updated_at = _now_ms()
            write_page(paths, page)
            updated_pages.append(page.id)

    # Delete the source itself
    os.unlink(source_path)

    # Rebuild index without the source slug
    entries = read_index(paths)
    entries = [e for e in entries if e[0] != source_id]
    if paths.llm_wiki_index.exists():
        os.unlink(paths.llm_wiki_index)
    if entries:
        append_to_index(paths, entries)

    _logger.info(
        f"[cascade_delete] deleted {source_id}; "
        f"updated {len(updated_pages)}, deleted {len(deleted_pages)}"
    )
    return {
        "deleted_source": True,
        "updated_pages": updated_pages,
        "deleted_pages": deleted_pages,
    }


def _now_ms() -> int:
    return int(time.time() * 1000)