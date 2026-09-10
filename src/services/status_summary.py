"""Web-facing adapter for the standalone status summary module."""
from __future__ import annotations

from collections import Counter

from ..lib.project import resolve_project
from ..status_summary import summarize_project


_STAGES = ("raw_status", "kc_status", "wiki_status", "book_status")


def get_status_summary(project_id: str) -> dict[str, object]:
    """Return a sanitized, project-scoped status snapshot for the WebUI."""
    ctx, paths = resolve_project(project_id, by_id_only=True)
    summary = summarize_project(paths.root)
    sources = [source.to_dict() for source in summary.sources]

    counts: dict[str, object] = {"sources": len(sources)}
    for field in _STAGES:
        stage = field.removesuffix("_status")
        counts[stage] = dict(Counter(source[field] for source in sources))

    return {
        "project": {"id": ctx.id, "name": ctx.name},
        "status": summary.status,
        "counts": counts,
        "pending_wiki_commits": summary.pending_wiki_commits,
        "build_runs": summary.build_runs,
        "sources": sources,
    }

