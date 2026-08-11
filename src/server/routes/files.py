# src/server/routes/files.py
from fastapi import APIRouter, HTTPException, UploadFile, File
from ...project.context import ProjectNotFoundError
from ...services import files as files_service

router = APIRouter(prefix="/api/v1", tags=["files"])


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str, root: str = "wiki", recursive: bool = True, max_files: int = 2000, include_tags: bool = False):
    """List markdown files in a project's wiki tree.

    Business logic lives in src.services.files; this route is a thin
    adapter that translates domain exceptions to HTTP status codes.
    """
    try:
        return files_service.list_files(project_id, root, recursive, max_files, include_tags)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/projects/{project_id}/files/content")
async def file_content(project_id: str, path: str):
    """Read the text content of a file within the project's wiki root."""
    try:
        return files_service.read_file_content(project_id, path)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except files_service.PathTraversalError as e:
        raise HTTPException(403, str(e))
    except files_service.FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except files_service.PathIsDirectoryError as e:
        raise HTTPException(400, str(e))
    except files_service.FileTooLargeError as e:
        raise HTTPException(413, str(e))


@router.get("/projects/{project_id}/raw-files")
async def raw_files(project_id: str):
    """List raw source files (PDF, DOCX, XLSX, etc.) under raw/sources/."""
    try:
        return files_service.list_raw_files(project_id)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/projects/{project_id}/upload")
async def upload_file(project_id: str, file: UploadFile = File(...)):
    """Upload a raw source file to ``raw/sources/``.

    The file is written to disk and can then be ingested via the normal
    ingest pipeline. Call ``POST /ingest`` with ``{"source": "<relpath>"}``
    afterwards, or use the batch-ingest UI to select it.
    """
    try:
        content = await file.read()
        return files_service.upload_file(project_id, file.filename or "upload", content)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
    except files_service.UnsupportedFileTypeError as e:
        raise HTTPException(400, str(e))
