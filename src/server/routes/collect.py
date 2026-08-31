"""HTTP routes for synchronous source collection."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ...collector.converter.exceptions import UnsupportedSourceError
from ...project.context import ProjectNotFoundError
from ...services import collect as collect_service
from ...services.collect import CollectPathError


router = APIRouter(prefix="/api/v1", tags=["collect"])
_UPLOAD_CHUNK_BYTES = 64 * 1024


class CollectUrlRequest(BaseModel):
    url: str


@router.post("/projects/{project_id}/collect")
async def collect_file(project_id: str, file: UploadFile = File(...)):
    from ...config import settings

    max_bytes = settings().max_upload_bytes
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"Upload exceeds limit of {max_bytes} bytes")
        chunks.append(chunk)

    try:
        return await collect_service.collect_file(
            project_id, file.filename or "upload", b"".join(chunks)
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (CollectPathError, UnsupportedSourceError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Collection failed: {exc}") from exc


@router.post("/projects/{project_id}/collect-url")
async def collect_url(project_id: str, body: CollectUrlRequest):
    try:
        return await collect_service.collect_url(project_id, body.url)
    except ProjectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UnsupportedSourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Collection failed: {exc}") from exc
