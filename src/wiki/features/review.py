"""Review items — async human judgment queue (A3)."""
import json
import time
import uuid
from pathlib import Path

from ..core.types import ReviewItem
from .tag_namespace import ACTIONABLE_TAG
from ...lib.write_hooks import safe_write


REVIEWS_FILE = ".index/reviews.json"
REVIEWS_RESOLVED_FILE = ".index/reviews_resolved.json"


class HumanReviewRequiredError(ValueError):
    """Raised when an actionable page has no valid human approval record."""


def _review_file(paths, resolved: bool = False) -> Path:
    name = REVIEWS_RESOLVED_FILE if resolved else REVIEWS_FILE
    return paths.root / name


def load_reviews(paths, resolved: bool = False) -> list[ReviewItem]:
    f = _review_file(paths, resolved)
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [ReviewItem(**item) for item in data.get("items", [])]


def save_reviews(paths, items: list[ReviewItem], resolved: bool = False) -> None:
    f = _review_file(paths, resolved)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "items": [_item_to_dict(i) for i in items]}
    safe_write(f, json.dumps(data, indent=2, ensure_ascii=False))


def _item_to_dict(item: ReviewItem) -> dict:
    return {
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "normalized_title": item.normalized_title,
        "detail": item.detail,
        "confidence": item.confidence,
        "search_queries": list(item.search_queries),
        "page_path": item.page_path,
        "created_at": item.created_at,
        "source_task_id": item.source_task_id,
        "status": item.status,
        "page_id": item.page_id,
        "reviewer": item.reviewer,
        "decision": item.decision,
        "decided_at": item.decided_at,
    }


def add_review(paths, type: str, title: str, **kwargs) -> ReviewItem:
    """Add a new review item; dedup by (type, normalized_title)."""
    normalized = " ".join(title.lower().split())
    items = load_reviews(paths)
    for it in items:
        if it.type == type and it.normalized_title == normalized:
            return it
    item = ReviewItem(
        id=str(uuid.uuid4())[:8],
        type=type,
        title=title,
        normalized_title=normalized,
        status="open",
        **kwargs,
    )
    items.append(item)
    save_reviews(paths, items)
    return item


def resolve_review(paths, item_id: str, action: str = "skip") -> None:
    """Move item from open → resolved."""
    items = load_reviews(paths)
    target = next((i for i in items if i.id == item_id), None)
    if target is None:
        return
    items = [i for i in items if i.id != item_id]
    save_reviews(paths, items)
    target.status = action  # "skip" | "fixed" | "merged"
    resolved = load_reviews(paths, resolved=True)
    resolved.append(target)
    save_reviews(paths, resolved, resolved=True)


def record_human_review(
    paths, page_id: str, reviewer: str, decision: str, decided_at: int | None = None,
) -> ReviewItem:
    """Record one human usage decision in the existing resolved review store."""
    reviewer = reviewer.strip() if isinstance(reviewer, str) else ""
    if not page_id or not reviewer:
        raise HumanReviewRequiredError("page_id and reviewer are required")
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    item = ReviewItem(
        id=f"usage-{uuid.uuid4().hex[:8]}",
        type="page-usage",
        title=page_id,
        normalized_title=page_id,
        detail="human usage decision",
        confidence=1.0,
        page_id=page_id,
        reviewer=reviewer,
        decision=decision,
        decided_at=decided_at or int(time.time() * 1000),
        status="resolved",
    )
    resolved = [
        existing for existing in load_reviews(paths, resolved=True)
        if not (existing.type == "page-usage" and existing.page_id == page_id)
    ]
    resolved.append(item)
    save_reviews(paths, resolved, resolved=True)
    return item


def has_approved_usage_review(paths, page_id: str) -> bool:
    return any(
        item.type == "page-usage"
        and item.page_id == page_id
        and item.reviewer
        and item.decision == "approved"
        and item.decided_at > 0
        for item in load_reviews(paths, resolved=True)
    )


def ensure_actionable_tag_review(paths, page_id: str, tags: list[str]) -> None:
    if ACTIONABLE_TAG in tags and not has_approved_usage_review(paths, page_id):
        raise HumanReviewRequiredError(
            f"{page_id}: {ACTIONABLE_TAG} requires an approved human review"
        )


def unresolve_review(paths, item_id: str) -> None:
    """Move item from resolved → open."""
    resolved = load_reviews(paths, resolved=True)
    target = next((i for i in resolved if i.id == item_id), None)
    if target is None:
        return
    resolved = [i for i in resolved if i.id != item_id]
    save_reviews(paths, resolved, resolved=True)
    target.status = "open"
    items = load_reviews(paths)
    items.append(target)
    save_reviews(paths, items)
