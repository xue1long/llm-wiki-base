"""Wiki template management HTTP API — 5 endpoints.

Corresponds to CLI subcommands: wiki-templates {list,show,edit,reset,status,diff,upgrade}.
Frontend-driven design: endpoints return what the UI needs to render.
"""

from fastapi import APIRouter, HTTPException

from ...project.context import ProjectNotFoundError
from ...lib.project import resolve_project

router = APIRouter(prefix="/api/v1", tags=["templates"])


@router.get("/projects/{project_id}/templates")
async def list_templates(project_id: str):
    """List all 4 PageType templates with source + version."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.templates import list_resolved
    templates = list_resolved(ctx.path)
    return {
        "templates": [
            {"type": t.type.value, "source": t.source, "version": t.version or "?"}
            for t in templates
        ]
    }


@router.get("/projects/{project_id}/templates/{type_name}")
async def get_template(project_id: str, type_name: str):
    """Get a single template's content."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.core.types import PageType
    try:
        page_type = PageType(type_name)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid type: {type_name}")

    from ...wiki.templates import resolve
    try:
        t = resolve(page_type, ctx.path)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"No template for {type_name}")

    return {
        "type": t.type.value,
        "source": t.source,
        "version": t.version or "?",
        "content": t.body_markdown,
    }


@router.post("/projects/{project_id}/templates/{type_name}")
async def edit_template(project_id: str, type_name: str, body: dict):
    """Save a template override for the project."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.core.types import PageType
    try:
        page_type = PageType(type_name)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid type: {type_name}")

    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(400, detail="Content is required")

    # Validate content has correct type header
    from ...wiki.templates.parser import validate_type_header, TemplateParseError
    try:
        validate_type_header(content, page_type)
    except TemplateParseError as e:
        raise HTTPException(400, detail=str(e))

    from ...wiki.templates.types import PROJECT_TEMPLATE_DIRNAME
    dest_dir = ctx.path / PROJECT_TEMPLATE_DIRNAME
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{type_name}.md"
    dest_path.write_text(content, encoding="utf-8")

    return {"ok": True, "type": type_name, "source": "project"}


@router.post("/projects/{project_id}/templates/{type_name}/reset")
async def reset_template(project_id: str, type_name: str):
    """Remove project-level template override, falling back to bundled."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.core.types import PageType
    try:
        page_type = PageType(type_name)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid type: {type_name}")

    from ...wiki.templates.types import PROJECT_TEMPLATE_DIRNAME
    target = ctx.path / PROJECT_TEMPLATE_DIRNAME / f"{type_name}.md"
    if not target.exists():
        raise HTTPException(404, detail=f"No project override for {type_name}")

    # Backup then remove
    backup = target.with_suffix(target.suffix + ".bak")
    import shutil
    shutil.copy2(target, backup)
    target.unlink()

    return {"ok": True, "type": type_name}


@router.get("/projects/{project_id}/templates/{type_name}/diff")
async def diff_template(project_id: str, type_name: str):
    """Diff project override against bundled."""
    try:
        ctx, paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        raise HTTPException(404, str(e))

    from ...wiki.core.types import PageType
    try:
        page_type = PageType(type_name)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid type: {type_name}")

    from ...wiki.templates.types import BUNDLED_DIR, PROJECT_TEMPLATE_DIRNAME
    import difflib

    project_path = ctx.path / PROJECT_TEMPLATE_DIRNAME / f"{type_name}.md"
    bundled_path = BUNDLED_DIR / f"{type_name}.md"

    if not project_path.is_file():
        return {"diff": [], "note": "no project override"}

    if not bundled_path.is_file():
        return {"diff": [], "note": "bundled template missing"}

    project_text = project_path.read_text(encoding="utf-8").splitlines(keepends=True)
    bundled_text = bundled_path.read_text(encoding="utf-8").splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        bundled_text, project_text,
        fromfile=f"bundled/{type_name}.md",
        tofile=f"project/{type_name}.md",
    ))

    return {"diff": diff_lines}
