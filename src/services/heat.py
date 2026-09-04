"""Heat lifecycle write operations — single service entry point (R10).

Audit: the HTTP heat routes and the heat CLI each hand-rolled
restore/archive writes against ``wiki.storage.page_writer`` (write_page)
and ``shutil.move``. R10 moves the write operations here so:

- routes stay thin adapters (resolve project → delegate → map errors);
- storage-layout changes touch one place, not two entry points;
- the same logic is unit-testable without HTTP or CLI plumbing.
"""
from __future__ import annotations

import shutil

from ..lib.project import resolve_project


def _infer_type(paths, slug):
    from ..wiki.core.types import PageType
    for t, dp in [
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SOURCE, "wiki_sources"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
    ]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE


def restore_zombies(project_id: str, page_ids: list[str]) -> dict:
    """Restore zombie pages: heat=100, immutable, clear zombie_since.

    Persists via ``write_page`` (AtomicContext-aware). Unknown page ids
    are ignored. Returns ``{"restored": N}``.
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    from ..wiki.storage.page_writer import read_page, write_page, page_path_for

    restored = 0
    for pid in page_ids:
        pf = page_path_for(paths, _infer_type(paths, pid), pid)
        if pf.exists():
            p = read_page(pf)
            p.heat = 100
            p.is_immutable = True
            p.zombie_since = None
            write_page(paths, p)
            restored += 1
    return {"restored": restored}


def archive_zombies(project_id: str, page_ids: list[str]) -> dict:
    """Move zombie pages into ``wiki/_archive/``.

    Uses a single AtomicContext batch so the moves commit atomically.
    Returns ``{"archived": N}``.
    """
    ctx, paths = resolve_project(project_id, by_id_only=True)
    from ..lib.atomic_ctx import AtomicContext
    from ..lib.write_hooks import flush_pending_writes
    from ..wiki.storage.page_writer import page_path_for

    archive_dir = paths.wiki / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived = 0
    with AtomicContext(flush_callback=flush_pending_writes):
        for pid in page_ids:
            pf = page_path_for(paths, _infer_type(paths, pid), pid)
            if pf.exists():
                shutil.move(str(pf), str(archive_dir / pf.name))
                archived += 1
    return {"archived": archived}
