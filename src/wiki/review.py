"""Wiki review queue — stub for HTTP API integration.

Provides load/add/resolve operations against the project's review-queue file.
Full implementation lives in a follow-up task; this module exists so routers
in src/server/routes/reviews.py can import the names they need.
"""
from pathlib import Path
from typing import Optional

from .types import ReviewItem


def _reviews_file(paths) -> Path:
    return paths.wiki / "_reviews.json"


def load_reviews(paths) -> list[ReviewItem]:
    """Load all reviews from project's review queue. Empty list if missing."""
    f = _reviews_file(paths)
    if not f.exists():
        return []
    import json
    data = json.loads(f.read_text(encoding="utf-8"))
    return [ReviewItem(**item) for item in data.get("reviews", [])]


def add_review(paths, review: ReviewItem) -> None:
    """Append a review to the project's review queue."""
    f = _reviews_file(paths)
    f.parent.mkdir(parents=True, exist_ok=True)
    import json
    data = {"reviews": []}
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"reviews": []}
    data["reviews"].append({
        "id": review.id,
        "type": review.type,
        "title": review.title,
        "normalized_title": review.normalized_title,
        "detail": review.detail,
        "confidence": review.confidence,
        "search_queries": list(review.search_queries),
        "page_path": review.page_path,
        "created_at": review.created_at,
        "source_task_id": review.source_task_id,
        "status": review.status,
    })
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_review(paths, review_id: str, action: str = "skip") -> bool:
    """Mark a review as resolved. Returns True if found and updated."""
    items = load_reviews(paths)
    found = False
    for item in items:
        if item.id == review_id:
            item.status = "resolved" if action == "resolve" else "dismissed"
            found = True
            break
    if not found:
        return False
    f = _reviews_file(paths)
    import json
    data = {
        "reviews": [
            {
                "id": i.id, "type": i.type, "title": i.title,
                "normalized_title": i.normalized_title, "detail": i.detail,
                "confidence": i.confidence, "search_queries": list(i.search_queries),
                "page_path": i.page_path, "created_at": i.created_at,
                "source_task_id": i.source_task_id, "status": i.status,
            }
            for i in items
        ]
    }
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True
