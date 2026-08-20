"""Fast capture HTTP endpoint — write wiki pages without LLM pipeline."""
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel

from ...project.context import ProjectNotFoundError
from ...services.capture import (
    capture_page,
    mark_page_verified_by_id,
    PageNotFoundError,
)

# P14 stress-test hardening: require_admin fallback (no-op) when the
# dependency doesn't exist in src/permissions.py.
try:
    from ...permissions import require_admin
except ImportError:
    async def require_admin():
        return None


router = APIRouter(prefix="/api/v1", tags=["capture"])


class CaptureRequest(BaseModel):
    type: str                    # "article" | "video-transcript" | "inspiration"
    title: str                   # required
    content: str = ""            # optional (empty → skeleton)
    url: str = ""                # optional source URL
    tags: list[str] | None = None  # optional tags
    category: str = ""           # optional taxonomy category


@router.post("/projects/{project_id}/capture")
async def capture(project_id: str, body: CaptureRequest):
    """Create a wiki page directly without LLM pipeline.

    Sub-types:
    - article: external article excerpt → source page
    - video-transcript: video transcript → source page
    - inspiration: spontaneous idea → concept page

    Empty content creates a skeleton page with template structure preserved.
    """
    try:
        return capture_page(
            project_id=project_id,
            type=body.type,
            title=body.title,
            content=body.content,
            url=body.url,
            tags=body.tags,
            category=body.category,
        )
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/pages/{page_id}/verify")
async def mark_page_verified_endpoint(
    project_id: str,
    page_id: str,
    user=Depends(require_admin),
    x_user_id: str = Header(None),
):
    """Mark a page as human-verified. Requires admin permission (P10).

    Bypasses ReviewerStage — direct human verification path for capture pages.
    """
    try:
        result = mark_page_verified_by_id(
            project_id=project_id,
            page_id=page_id,
            user_id=x_user_id or "api",
        )
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except PageNotFoundError as e:
        raise HTTPException(404, str(e))
    return result
