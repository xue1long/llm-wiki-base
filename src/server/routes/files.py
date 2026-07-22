# src/server/routes/files.py
from fastapi import APIRouter, HTTPException
from ...services import files as files_service

router = APIRouter(prefix="/api/v1", tags=["files"])


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str, root: str = "wiki", recursive: bool = True, max_files: int = 2000):
    """List markdown files in a project's wiki tree.

    Business logic lives in src.services.files; this route is a thin
    adapter that translates domain exceptions to HTTP status codes.
    """
    return files_service.list_files(project_id, root, recursive, max_files)


@router.get("/projects/{project_id}/files/content")
async def file_content(project_id: str, path: str):
    """Read the text content of a file within the project's wiki root."""
    try:
        return files_service.read_file_content(project_id, path)
    except files_service.PathTraversalError as e:
        raise HTTPException(403, str(e))
    except files_service.FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except files_service.PathIsDirectoryError as e:
        raise HTTPException(400, str(e))
    except files_service.FileTooLargeError as e:
        raise HTTPException(413, str(e))
