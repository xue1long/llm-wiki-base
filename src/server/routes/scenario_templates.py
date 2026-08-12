"""Scenario-template management HTTP endpoints."""
from fastapi import APIRouter, HTTPException

from ...templates import create, delete, list_templates, load, update_content, update_metadata

router = APIRouter(prefix="/api/v1/scenario-templates", tags=["scenario-templates"])


def _payload(t):
    return {
        "id": t.name, "name": t.name, "description": t.description,
        "icon": t.icon, "builtin": t.builtin, "files": t.files,
        "extra_dirs": t.extra_dirs or [],
    }


@router.get("")
async def list_scenario_templates():
    return {"templates": [_payload(t) for t in list_templates()]}


@router.get("/{template_id}")
async def get_scenario_template(template_id: str):
    try:
        return _payload(load(template_id))
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc))


@router.post("")
async def create_scenario_template(body: dict):
    try:
        return _payload(create(
            body.get("id", ""), source=body.get("source", "general"),
            description=body.get("description", ""), icon=body.get("icon", ""),
        ))
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        raise HTTPException(400, str(exc))


@router.put("/{template_id}")
async def update_scenario_template(template_id: str, body: dict):
    try:
        update_content(template_id, body.get("files", {}), extra_dirs=body.get("extra_dirs"))
        return _payload(update_metadata(
            template_id, description=body.get("description"), icon=body.get("icon")
        ))
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{template_id}")
async def delete_scenario_template(template_id: str):
    try:
        delete(template_id)
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}
