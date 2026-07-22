"""Review queue list + resolve.

Extracted from src/server/routes/reviews.py. Wraps the wiki.review
JSON-file-backed queue with HTTP-friendly filters and a thin
domain exception layer.
"""
from __future__ import annotations

from typing import Optional

from ..lib.project import resolve_project
from ..wiki.review import load_reviews, resolve_review as _wiki_resolve


def list_reviews(
    project_id: str,
    status: str = "open",
    type: Optional[str] = None,
    limit: int = 200,
) -> dict:
    """List review items for a project, with optional filters.

    Returns a dict ready to be returned from an HTTP route:
        {"status": str, "count": int, "reviews": [...]}
    """
    _ctx, paths = resolve_project(project_id, by_id_only=True)
    items = load_reviews(paths)
    if status != "all":
        items = [i for i in items if i.status == status]
    if type:
        items = [i for i in items if i.type == type]
    items = items[:limit]
    return {
        "status": status,
        "count": len(items),
        "reviews": [
            {
                "id": i.id,
                "type": i.type,
                "title": i.title,
                "normalizedTitle": i.normalized_title,
                "detail": i.detail,
                "confidence": i.confidence,
                "searchQueries": i.search_queries,
                "pagePath": i.page_path,
                "createdAt": i.created_at,
                "sourceTaskId": i.source_task_id,
                "status": i.status,
            }
            for i in items
        ],
    }


def resolve_review(project_id: str, review_id: str, action: str = "skip") -> None:
    """Mark a review as resolved (moved to resolved queue with action label)."""
    _ctx, paths = resolve_project(project_id, by_id_only=True)
    _wiki_resolve(paths, review_id, action)
