"""Fast capture HTTP endpoint — write wiki pages without LLM pipeline."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...project.context import ProjectNotFoundError
from ...services.capture import capture_page

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
