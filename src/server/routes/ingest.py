# src/server/routes/ingest.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Union
from ...project.context import ProjectNotFoundError
from ...services import ingest as ingest_service
from ...services.ingest import IngestPathError

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: Union[str, dict]   # URL or {"folder": path}
    folderContext: str | None = None


@router.post("/projects/{project_id}/ingest")
async def ingest(project_id: str, body: IngestRequest):
    """Enqueue a URL or folder path for ingestion."""
    try:
        return ingest_service.enqueue_source(project_id, body.source, body.folderContext)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except IngestPathError as e:
        # Per services/ingest.IngestPathError docstring: the service
        # raises this for absolute paths outside the project root.
        # Surface as HTTP 400 (client error) rather than the default
        # 500 the unhandled exception would produce.
        raise HTTPException(400, str(e))
