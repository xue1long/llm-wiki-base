# src/server/routes/providers.py
"""HTTP routes for LLM provider management."""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...llm.registry import ProviderRegistry, ProviderNotFoundError
from ...llm.types import ProviderConfig

router = APIRouter(prefix="/api/v1", tags=["providers"])


def _config_to_dict(cfg: ProviderConfig, redact_keys: bool = True) -> dict[str, Any]:
    """ProviderConfig -> dict with api_key redacted for list/show.

    R1: the API never returns the raw API key. ``redact_keys`` is kept as
    a parameter only for internal callers that explicitly need the raw
    value *within* the server process; every HTTP response must use the
    default (redacted) form.
    """
    d = cfg.to_dict()
    if redact_keys:
        d["api_key"] = "***" if d.get("api_key") else ""
    return d


class AddProviderRequest(BaseModel):
    name: str
    type: str | None = None  # openai | anthropic | ollama | openai-compatible
    api_key: str | None = None
    base_url: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None


class SetDefaultRequest(BaseModel):
    name: str


def _fields_set(body: BaseModel) -> set[str]:
    """Return fields explicitly sent by the client across Pydantic versions."""
    fields = getattr(body, "model_fields_set", None)
    if fields is None:
        fields = getattr(body, "__fields_set__", set())
    return set(fields)


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name or any(ch in name for ch in "/\\") or any(
        ord(ch) < 32 for ch in name
    ):
        raise HTTPException(400, "Provider name must be non-empty and path-safe")
    return name


@router.get("/providers")
def list_providers() -> dict:
    """List all configured providers."""
    providers = ProviderRegistry.load()
    default_name = None
    default_error = None
    try:
        default_name = ProviderRegistry.get_default().name
    except (ProviderNotFoundError, ValueError) as exc:
        default_error = str(exc)
    result = {
        "providers": [
            {**_config_to_dict(p), "is_default": p.name == default_name}
            for p in providers.values()
        ]
    }
    if default_error:
        result["default_error"] = default_error
    return result


@router.get("/providers/{name}")
def get_provider(name: str) -> dict:
    """Get a single provider config (API key always redacted — R1)."""
    try:
        config = ProviderRegistry.require(name)
    except (ProviderNotFoundError, ValueError):
        raise HTTPException(404, f"Provider not found: {name}")
    return {"ok": True, "provider": _config_to_dict(config)}


@router.post("/providers")
def add_provider(body: AddProviderRequest) -> dict:
    """Add or update a provider."""
    name = _validate_name(body.name)
    fields = _fields_set(body)
    try:
        existing = ProviderRegistry.require(name)
    except ProviderNotFoundError:
        existing = None

    if "api_key" in fields and body.api_key is None:
        raise HTTPException(400, "api_key cannot be null")
    if body.api_key == "***":
        raise HTTPException(400, "api_key must be omitted when unchanged")

    if "type" in fields and body.type is None:
        raise HTTPException(400, "type cannot be null")
    provider_type = body.type if body.type is not None else (
        existing.type if existing else None
    )
    if provider_type not in ("openai", "anthropic", "ollama", "openai-compatible"):
        raise HTTPException(400, f"Unknown provider type: {provider_type}")

    def value(field: str, default: str = "") -> str:
        raw = getattr(body, field)
        if field in fields:
            if raw is None:
                raise HTTPException(400, f"{field} cannot be null")
            return raw
        return getattr(existing, field, default)

    base_url = value("base_url")
    if provider_type == "ollama" and not base_url:
        base_url = "http://127.0.0.1:11434"

    # An omitted or empty key preserves an existing key. There is no HTTP
    # clear-key operation in this phase.
    api_key = body.api_key or getattr(existing, "api_key", "")

    config = ProviderConfig(
        name=name,
        type=provider_type,
        base_url=base_url,
        api_key=api_key,
        models=dict(getattr(existing, "models", {})),
        default_chat_model=value("chat_model"),
        default_embedding_model=value("embedding_model"),
        timeout_seconds=getattr(existing, "timeout_seconds", 120),
        extra_headers=dict(getattr(existing, "extra_headers", {})),
        extra_body=dict(getattr(existing, "extra_body", {})),
        sourced_from_env=bool(getattr(existing, "sourced_from_env", False))
        and not body.api_key,
    )
    ProviderRegistry.upsert(config)
    return {"ok": True, "provider": _config_to_dict(config)}


@router.delete("/providers/{name}")
def remove_provider(name: str) -> dict:
    try:
        current_default = ProviderRegistry.get_default()
    except (ProviderNotFoundError, ValueError) as exc:
        raise HTTPException(409, f"Cannot resolve default provider: {exc}")
    if current_default.name == name:
        raise HTTPException(409, "Switch the default provider before deleting it")
    try:
        removed = ProviderRegistry.remove(name)
    except (ProviderNotFoundError, ValueError):
        raise HTTPException(404, f"Provider not found: {name}")
    if not removed:
        raise HTTPException(404, f"Provider not found: {name}")
    return {"ok": True}


@router.post("/providers/set-default")
def set_default_provider(body: SetDefaultRequest) -> dict:
    """Set the explicit default provider in the registry."""
    try:
        ProviderRegistry.set_default(body.name)
    except ProviderNotFoundError:
        raise HTTPException(404, f"Provider not found: {body.name}")
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
            health = await provider.health_check()
            if health.get("ok"):
                rf = await provider.check_response_format()
                health["response_format_ok"] = rf.get("ok", False)
                health["response_format_detail"] = rf.get("detail", "")
            return provider, health
        finally:
            await provider.close()

    try:
        _, health = asyncio.run(_run())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    result = {"ok": health.get("ok", False), "detail": health.get("detail", "")}
    rf_ok = health.get("response_format_ok")
    if rf_ok is not None:
        result["response_format_ok"] = rf_ok
        result["response_format_detail"] = health.get("response_format_detail", "")
    return result
