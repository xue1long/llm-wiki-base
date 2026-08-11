"""cascade_delete — remove a source page and clean up all dependents.

When a source is deleted, any entity/concept/synthesis page that references
any of its source paths must either be updated (drop the reference) or
deleted entirely (if it has no other sources). The wiki index is also
rebuilt without the source slug.

I-pipeline-2 fix (T8 partial): cascade_delete now opens its own
atomic_pipeline_op() internally so callers do NOT need to wrap it. The
internal safe_write() calls are buffered until the function returns; on
exception the buffered writes are dropped and the wiki is unchanged. If
the caller also wraps us, the inner AtomicContext is a no-op (only the
outer call to AtomicContext actually flushes on exit).
"""
import logging
import time

from ...lib.write_hooks import DELETE_SENTINEL, safe_write
from ..storage.atomic_ctx_helpers import atomic_pipeline_op

from ..storage.ensure import ensure_knowledge_base
from .indexer import read_index
from ..storage.page_writer import read_page, write_page, page_path_for
from ..core.paths import WikiPaths
from ..core.types import WikiPage

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
        - Opens its own atomic_pipeline_op() so partial failure leaves the
          wiki unchanged. Callers MAY also wrap us in atomic_pipeline_op;
          the inner context is a no-op.

    Returns:
        {"deleted_source": bool, "updated_pages": list[str],
         "deleted_pages": list[str]}
    """
    # Open our own atomic context FIRST (T8 I-pipeline-2 auditfix).
    # This is the first executable line so that all setup, validation, and
    # the actual cascade work happens INSIDE the context. On context exit,
    # either all changes commit or none do. The caller no longer needs to
    # wrap us; a redundant outer wrapper is a safe no-op.
    with atomic_pipeline_op(paths):
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
                    safe_write(page_file, DELETE_SENTINEL)
                deleted_pages.append(page.id)
            else:
                page.sources = new_sources
                page.updated_at = _now_ms()
                write_page(paths, page)
                updated_pages.append(page.id)

        # Delete the source itself
        safe_write(source_path, DELETE_SENTINEL)

        # Rebuild index without the source slug — write the full set from scratch
        # so the on-disk stale entries don't suppress our rewrite via dedup.
        entries = [e for e in read_index(paths) if e[0] != source_id]
        from .indexer import INDEX_HEADER, _format_entry
        if entries:
            content = INDEX_HEADER + "".join(_format_entry(s, t, ttl) for s, t, ttl in entries)
            safe_write(paths.llm_wiki_index, content)
        elif paths.llm_wiki_index.exists():
            safe_write(paths.llm_wiki_index, DELETE_SENTINEL)

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
