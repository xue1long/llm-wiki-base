# src/server/routes/files.py
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
from ...project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["files"])


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str, root: str = "wiki", recursive: bool = True, max_files: int = 2000):
    ctx = _resolve_ctx(project_id)
    base = getattr(ctx.paths, f"wiki_{root.rstrip('s') if root != 'sources' else 'sources'}", None) or ctx.paths.wiki / root
    if not base.exists():
        return {"files": [], "truncated": False, "totalCount": 0}
    files = list(base.rglob("*.md")) if recursive else list(base.glob("*.md"))
    truncated = len(files) > max_files
    files = files[:max_files]
    return {
        "files": [
            {"path": str(f.relative_to(ctx.path)), "isDir": False, "size": f.stat().st_size}
            for f in files
        ],
        "truncated": truncated,
        "totalCount": len(files),
    }


@router.get("/projects/{project_id}/files/content")
async def file_content(project_id: str, path: str):
    ctx = _resolve_ctx(project_id)
    file_path = ctx.path / path
    if not file_path.exists():
        raise HTTPException(404, f"File not found: {path}")
    if file_path.stat().st_size > 2_000_000:
        raise HTTPException(413, "File too large (> 2MB)")
    return {
        "path": path,
        "content": file_path.read_text(encoding="utf-8"),
        "truncated": False,
        "size": file_path.stat().st_size,
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
