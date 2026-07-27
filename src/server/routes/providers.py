# src/server/routes/providers.py
"""HTTP routes for LLM provider management."""
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...llm.registry import ProviderRegistry, ProviderNotFoundError
from ...llm.types import ModelInfo, ProviderConfig

router = APIRouter(prefix="/api/v1", tags=["providers"])


def _config_to_dict(cfg: ProviderConfig, redact_keys: bool = True) -> dict[str, Any]:
    """ProviderConfig -> dict with api_key redacted for list/show."""
    d = cfg.to_dict()
    if redact_keys:
        d["api_key"] = "***" if d.get("api_key") else ""
    return d


class AddProviderRequest(BaseModel):
    name: str
    type: str  # openai | anthropic | ollama
    api_key: str = ""
    base_url: str = ""
    chat_model: str = ""
    embedding_model: str = ""


class SetDefaultRequest(BaseModel):
    name: str


def _default_provider_name() -> str | None:
    env_file = Path(os.path.expanduser("~/.config/ruflo-kb/env"))
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("RUFLO_LLM_PROVIDER="):
            return line.split("=", 1)[1].strip()
    return None


@router.get("/providers")
def list_providers() -> dict:
    """List all configured providers."""
    providers = ProviderRegistry.load()
    default_name = _default_provider_name()
    return {
        "providers": [
            {**_config_to_dict(p), "is_default": p.name == default_name}
            for p in providers.values()
        ]
    }


@router.post("/providers")
def add_provider(body: AddProviderRequest) -> dict:
    """Add or update a provider."""
    if body.type not in ("openai", "anthropic", "ollama"):
        raise HTTPException(400, f"Unknown provider type: {body.type}")

    base_url = body.base_url
    if body.type == "ollama" and not base_url:
        base_url = "http://127.0.0.1:11434"

    models: dict[str, ModelInfo] = {}
    if body.chat_model:
        models[body.chat_model] = ModelInfo(name=body.chat_model)

    config = ProviderConfig(
        name=body.name,
        type=body.type,
        base_url=base_url,
        api_key=body.api_key,
        models=models,
        default_chat_model=body.chat_model,
        default_embedding_model=body.embedding_model or body.chat_model,
    )
    ProviderRegistry.upsert(config)
    return {"ok": True, "provider": _config_to_dict(config, redact_keys=False)}


@router.delete("/providers/{name}")
def remove_provider(name: str) -> dict:
    try:
        ProviderRegistry.remove(name)
    except ProviderNotFoundError:
        raise HTTPException(404, f"Provider not found: {name}")
    return {"ok": True}


@router.post("/providers/set-default")
def set_default_provider(body: SetDefaultRequest) -> dict:
    """Set the default provider by writing to ~/.config/ruflo-kb/env."""
    try:
        ProviderRegistry.require(body.name)
    except ProviderNotFoundError:
        raise HTTPException(404, f"Provider not found: {body.name}")

    config_dir = Path(os.path.expanduser("~/.config/ruflo-kb"))
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / "env"
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    lines = [l for l in existing.splitlines() if not l.startswith("RUFLO_LLM_PROVIDER=")]
    lines.append(f"RUFLO_LLM_PROVIDER={body.name}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True}


@router.post("/providers/test")
def test_provider(name: str) -> dict:
    """Test connectivity to a provider."""
    import asyncio
    from ...llm.provider_factory import _create_from_config

    try:
        config = ProviderRegistry.require(name)
    except ProviderNotFoundError:
        raise HTTPException(404, f"Provider not found: {name}")

    async def _run():
        provider = _create_from_config(config)
        try:
            return provider, await provider.health_check()
        finally:
            await provider.close()

    try:
        _, health = asyncio.run(_run())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": health.get("ok", False), "detail": health.get("detail", "")}
