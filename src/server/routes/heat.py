"""Heat management HTTP API — 4 endpoints for wiki heat decay lifecycle.

Corresponds to CLI subcommands: heat {show,top,decay,zombies,restore,archive}.
"""
from fastapi import APIRouter, HTTPException

from ...project.context import ProjectNotFoundError
from ...lib.project import resolve_project

router = APIRouter(prefix="/api/v1", tags=["heat"])


@router.get("/projects/{project_id}/heat")
async def get_heat(project_id: str):
    """Return heat pools summary + top pages + zombies list.

    Response shape (frontend-driven):
      { pools: {hot, warm, cold, zombie}, top: [...], zombies: [...] }
    """
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.storage.page_writer import read_page, page_path_for
    from ...wiki.core.types import PageType

    pages = []
    for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                  (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        for f in getattr(paths, dp).glob("*.md"):
            p = read_page(f)
            pages.append(p)

    pools = {"hot": 0, "warm": 0, "cold": 0, "zombie": 0}
    for p in pages:
        if p.zombie_since:
            pools["zombie"] += 1
        elif p.heat >= 80:
            pools["hot"] += 1
        elif p.heat >= 40:
            pools["warm"] += 1
        else:
            pools["cold"] += 1

    pages.sort(key=lambda p: -p.heat)
    top = [
        {
            "rank": i + 1,
            "heat": p.heat,
            "type": p.type.value,
            "title": p.title,
            "path": str(page_path_for(paths, p.type, p.id).relative_to(paths.wiki)),
        }
        for i, p in enumerate(pages[:10])
    ]

    from ...wiki.features.zombie import ZombieDetector
    zombies_raw = ZombieDetector.list_zombies(paths)
    zombies = [
        {
            "page_id": z["id"],
            "title": z.get("title", z["id"]),
            "path": f"{z['id']}.md",
            "zombie_since": z["zombie_since"],
        }
        for z in zombies_raw
    ]

    return {"pools": pools, "top": top, "zombies": zombies}


@router.post("/projects/{project_id}/heat/decay")
async def decay_heat(project_id: str):
    """Trigger heat decay sweep. Returns {decayed, zombies_created}."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...services.wiki_analysis import get_heat_tracker
    tracker = get_heat_tracker(paths)
    events = tracker.decay()

    zombies_created = sum(1 for e in events if e.reason == "decay" and e.delta < 0)
    return {"decayed": len(events), "zombies_created": zombies_created}


@router.post("/projects/{project_id}/heat/zombies/restore")
async def restore_zombies(project_id: str, body: dict):
    """Restore zombie pages. Expects body: {page_ids: [...]}.

    R10: delegates the write to src.services.heat (thin adapter).
    """
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...services.heat import restore_zombies as _restore
    return _restore(project_id, body.get("page_ids", []))


@router.post("/projects/{project_id}/heat/zombies/archive")
async def archive_zombies(project_id: str, body: dict):
    """Archive zombie pages to _archive/. Expects body: {page_ids: [...]}.

    R10: delegates the write to src.services.heat (thin adapter).
    """
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...services.heat import archive_zombies as _archive
    return _archive(project_id, body.get("page_ids", []))
