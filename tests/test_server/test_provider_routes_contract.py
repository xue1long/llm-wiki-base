"""HTTP seam tests for the Provider settings contract."""

import pytest
from fastapi import HTTPException

from src.llm.registry import ProviderNotFoundError
from src.llm.types import ModelInfo, ProviderConfig
from src.server.routes import providers as provider_routes


def _config(name="p1", **kwargs):
    return ProviderConfig(name=name, type="openai", **kwargs)


def test_set_default_uses_registry_slot_not_env_file(monkeypatch):
    called = []
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "require",
        lambda name: _config(name),
    )
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "set_default",
        lambda name: called.append(name),
    )

    result = provider_routes.set_default_provider(
        provider_routes.SetDefaultRequest(name="p1")
    )

    assert result == {"ok": True}
    assert called == ["p1"]


def test_list_marks_resolved_registry_default(monkeypatch):
    config = _config()
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "load",
        lambda: {config.name: config},
    )
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "get_default",
        lambda: config,
    )

    result = provider_routes.list_providers()

    assert result["providers"][0]["is_default"] is True


def test_remove_rejects_current_default_before_mutating(monkeypatch):
    config = _config()
    removed = []
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "get_default",
        lambda: config,
    )
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "remove",
        lambda name: removed.append(name),
    )

    with pytest.raises(HTTPException) as exc:
        provider_routes.remove_provider("p1")

    assert exc.value.status_code == 409
    assert removed == []


def test_masked_api_key_is_rejected_on_update(monkeypatch):
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "require",
        lambda name: _config(name, api_key="sk-real"),
    )

    with pytest.raises(HTTPException) as exc:
        provider_routes.add_provider(
            provider_routes.AddProviderRequest(
                name="p1",
                type="openai",
                api_key="***",
            )
        )

    assert exc.value.status_code == 400


def test_update_preserves_key_hidden_fields_and_two_model_defaults(monkeypatch):
    existing = _config(
        api_key="sk-real",
        models={"legacy": ModelInfo(name="legacy")},
        default_chat_model="old-chat",
        default_embedding_model="old-embedding",
        timeout_seconds=7,
        extra_headers={"X-Trace": "1"},
        extra_body={"custom": True},
    )
    saved = []
    monkeypatch.setattr(provider_routes.ProviderRegistry, "require", lambda name: existing)
    monkeypatch.setattr(provider_routes.ProviderRegistry, "upsert", saved.append)

    result = provider_routes.add_provider(
        provider_routes.AddProviderRequest(
            name="p1",
            type="openai",
            api_key="",
            chat_model="new-chat",
            embedding_model="new-embedding",
        )
    )

    config = saved[0]
    assert result["provider"]["api_key"] == "***"
    assert config.api_key == "sk-real"
    assert config.default_chat_model == "new-chat"
    assert config.default_embedding_model == "new-embedding"
    assert config.timeout_seconds == 7
    assert config.extra_headers == {"X-Trace": "1"}
    assert config.extra_body == {"custom": True}


def test_update_rejects_null_and_invalid_provider_names(monkeypatch):
    monkeypatch.setattr(
        provider_routes.ProviderRegistry, "require", lambda name: _config(name)
    )

    with pytest.raises(HTTPException) as null_exc:
        provider_routes.add_provider(
            provider_routes.AddProviderRequest(name="p1", type="openai", base_url=None)
        )
    assert null_exc.value.status_code == 400

    with pytest.raises(HTTPException) as name_exc:
        provider_routes.add_provider(
            provider_routes.AddProviderRequest(name="bad/name", type="openai")
        )
    assert name_exc.value.status_code == 400


def test_list_reports_default_resolution_error_without_guessing(monkeypatch):
    config = _config()
    monkeypatch.setattr(
        provider_routes.ProviderRegistry, "load", lambda: {config.name: config}
    )
    monkeypatch.setattr(
        provider_routes.ProviderRegistry,
        "get_default",
        lambda: (_ for _ in ()).throw(ProviderNotFoundError("missing")),
    )

    result = provider_routes.list_providers()

    assert "default_error" in result
    assert result["providers"][0]["is_default"] is False
