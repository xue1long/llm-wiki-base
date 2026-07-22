# src/server/routes/files.py
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
from ...project.context import ProjectContext, ProjectNotFoundError

router = APIRouter(prefix="/api/v1", tags=["files"])


def _resolve_root(ctx, root: str) -> Path:
    """Resolve the listing root within the project's wiki tree.

    Prevents the previous ``getattr(ctx.paths, f"wiki_{root.rstrip('s')}...")``
    bug that produced ``wiki_wiki`` for ``root="wiki"``. Explicit mapping:
    - ``root == "wiki"``    -> ``ctx.paths.wiki``
    - ``root == "sources"`` -> ``ctx.paths.sources``
    - anything else          -> subdirectory under ``ctx.paths.wiki``
    """
    if root == "wiki":
        return ctx.paths.wiki
    if root == "sources":
        return ctx.paths.sources
    return ctx.paths.wiki / root


@router.get("/projects/{project_id}/files")
async def list_files(project_id: str, root: str = "wiki", recursive: bool = True, max_files: int = 2000):
    ctx = _resolve_ctx(project_id)
    base = _resolve_root(ctx, root)
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
    base = _resolve_root(ctx, "wiki")
    candidate = (base / path).resolve()
    # Path-traversal guard: the resolved file must remain under the wiki root.
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(403, f"Path escapes project root: {path}")
    if not candidate.exists():
        raise HTTPException(404, f"File not found: {path}")
    if candidate.is_dir():
        raise HTTPException(400, f"Path is a directory: {path}")
    size = candidate.stat().st_size
    if size > 2_000_000:
        raise HTTPException(413, "File too large (> 2MB)")
    return {
        "path": path,
        "content": candidate.read_text(encoding="utf-8"),
        "truncated": False,
        "size": size,
    }


def _resolve_ctx(project_id: str) -> ProjectContext:
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))
