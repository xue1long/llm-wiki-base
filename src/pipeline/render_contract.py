"""Untrusted, non-persistent render output exchanged before compilation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderDraft:
    task_id: str
    source_id: str
    page_key: str
    ordinal: int
    template_version: str
    title: str
    page_type: str
    body: str
    candidate_links: tuple[str, ...] = ()
    candidate_tags: tuple[str, ...] = ()
    referenced_block_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderBundle:
    task_id: str
    source_id: str
    template_version: str
    pages: tuple[RenderDraft, ...]
    bundle_hash: str = ""

    def __post_init__(self) -> None:
        if not self.bundle_hash:
            object.__setattr__(self, "bundle_hash", self.compute_hash())

    def compute_hash(self) -> str:
        payload = {
            "task_id": self.task_id,
            "source_id": self.source_id,
            "template_version": self.template_version,
            "pages": [page.__dict__ for page in self.pages],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def render_candidate(candidate, context: dict) -> RenderBundle:
    """Convert candidate page-shaped data into an immutable, untrusted bundle."""
    task_id = str(context["task_id"])
    source_id = str(candidate.get("source_id", context.get("source_id", "")))
    template_version = str(context["template_version"])
    drafts = []
    for ordinal, page in enumerate(candidate.get("pages", [candidate])):
        drafts.append(RenderDraft(
            task_id=task_id,
            source_id=source_id,
            page_key=str(page.get("page_key") or page.get("key") or f"page-{ordinal}"),
            ordinal=ordinal,
            template_version=template_version,
            title=str(page.get("title", "")),
            page_type=str(page.get("page_type", page.get("type", ""))),
            body=str(page.get("body", page.get("body_markdown", ""))),
            candidate_links=tuple(str(x) for x in page.get("links", page.get("candidate_links", ()))),
            candidate_tags=tuple(str(x) for x in page.get("tags", page.get("candidate_tags", ()))),
            referenced_block_ids=tuple(str(x) for x in page.get("referenced_block_ids", ())),
            warnings=tuple(str(x) for x in page.get("warnings", ())),
        ))
    return RenderBundle(task_id, source_id, template_version, tuple(drafts))


def render_pages(pages, *, task_id: str, source_id: str, template_version: str) -> RenderBundle:
    """Adapt legacy in-memory page results without making them persistent."""
    return render_candidate({
        "source_id": source_id,
        "pages": [{
            "page_key": getattr(page, "id", None) or f"page-{ordinal}",
            "title": getattr(page, "title", ""),
            "type": getattr(getattr(page, "type", ""), "value", getattr(page, "type", "")),
            "body": getattr(page, "body", ""),
            "tags": tuple(getattr(page, "tags", ()) or ()),
        } for ordinal, page in enumerate(pages)],
    }, {"task_id": task_id, "template_version": template_version})


__all__ = ["RenderBundle", "RenderDraft", "render_candidate", "render_pages"]
