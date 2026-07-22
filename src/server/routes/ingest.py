# src/server/routes/ingest.py
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Union
from ...services import ingest as ingest_service

router = APIRouter(prefix="/api/v1", tags=["ingest"])


class IngestRequest(BaseModel):
    source: Union[str, dict]   # URL or {"folder": path}
    folderContext: str | None = None


@router.post("/projects/{project_id}/ingest")
async def ingest(project_id: str, body: IngestRequest):
    """Enqueue a URL or folder path for ingestion."""
    return ingest_service.enqueue_source(project_id, body.source, body.folderContext)
