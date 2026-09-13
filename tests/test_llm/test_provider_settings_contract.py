"""Contract tests for the Provider settings migration."""

import json

import pytest

from src.llm.registry import ProviderNotFoundError, ProviderRegistry
from src.llm.types import ProviderConfig


def _write_registry(path, providers, default=None):
    payload = {"providers": {name: cfg.to_dict() for name, cfg in providers.items()}}
    if default is not None:
        payload["default"] = default
    path.write_text(json.dumps(payload), encoding="utf-8")


def _provider(name, type_, **kwargs):
    return ProviderConfig(name=name, type=type_, **kwargs)


def test_explicit_default_wins_over_legacy_env(tmp_path, monkeypatch):
    """The persisted explicit default is authoritative over legacy env."""
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    _write_registry(
        cfg_path,
        {
            "openai": _provider("openai", "openai"),
            "ollama": _provider("ollama", "ollama"),
        },
        default="ollama",
    )
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "openai")

    assert ProviderRegistry.get_default().name == "ollama"


def test_explicit_default_missing_fails_without_env_fallback(tmp_path, monkeypatch):
    """A dangling explicit default must not silently select another provider."""
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    _write_registry(
        cfg_path,
        {"openai": _provider("openai", "openai")},
        default="missing",
    )
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "openai")

    with pytest.raises(ProviderNotFoundError, match="missing"):
        ProviderRegistry.get_default()


def test_upsert_preserves_explicit_default(tmp_path, monkeypatch):
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    providers = {
        "openai": _provider("openai", "openai"),
        "ollama": _provider("ollama", "ollama"),
    }
    ProviderRegistry.save(providers)
    ProviderRegistry.set_default("ollama")

    ProviderRegistry.upsert(_provider("openai", "openai", base_url="https://new"))

    assert ProviderRegistry.get_default().name == "ollama"
    assert ProviderRegistry.get_default_name() == "ollama"
