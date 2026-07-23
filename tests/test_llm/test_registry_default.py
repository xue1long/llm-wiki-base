"""Regression tests for audit finding: default provider selection must
honour explicit is_default flags, not just env var or insertion order.

Problem: ``ProviderRegistry.get_default()`` falls back to
``next(iter(providers.values()))`` when no provider is named "default".
When providers are sourced from env vars (``sourced_from_env=True``),
none of them carry an explicit ``is_default`` flag, so the first
insertion wins — which on this host is OpenAI even though the user has
configured Ollama via ``llm-providers add ollama ollama --model ...``.

Fix: when multiple providers exist and none has is_default=True, prefer
the persisted (non-env) provider that the user added explicitly.
"""
import json
from pathlib import Path

import pytest

from src.llm.types import ProviderConfig
from src.llm.registry import ProviderRegistry


def _write_registry(path: Path, providers: dict) -> None:
    """Write a synthetic providers.json for the test."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "providers": {
            name: {**cfg.to_dict(), "sourced_from_env": cfg.sourced_from_env}
            for name, cfg in providers.items()
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_config(name, type_, *, sourced_from_env=False, base_url="",
                 default_chat_model="", api_key=""):
    return ProviderConfig(
        name=name,
        type=type_,
        base_url=base_url,
        api_key=api_key,
        default_chat_model=default_chat_model,
        sourced_from_env=sourced_from_env,
    )


def test_get_default_prefers_explicitly_added_when_no_env_override(
    tmp_path, monkeypatch
):
    """When no env var is set and no provider is named 'default', the
    explicitly-added (non-env) provider should win over the env-sourced one.

    Realistic registry contents:
      - openai: from env var, blank api_key after save, default model/base_url
      - ollama: user-added with a custom base_url + model → distinct from
        the env-derived default that happens to also be called 'ollama'.
    """
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)

    _write_registry(
        cfg_path,
        {
            # Env-sourced: matches the default config exactly.
            "openai": _make_config(
                "openai", "openai",
                sourced_from_env=True,
                base_url="https://api.openai.com/v1",
                default_chat_model="gpt-4o-mini",
            ),
            # User-added with a custom model — differs from the env default.
            "ollama": _make_config(
                "ollama", "ollama",
                sourced_from_env=False,
                base_url="http://127.0.0.1:11434",
                default_chat_model="qwen3.5-9b-custom",
            ),
        },
    )
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)

    chosen = ProviderRegistry.get_default()
    assert chosen.name == "ollama", (
        f"explicitly-added ollama should be the default, got {chosen.name!r}. "
        "ProviderRegistry.get_default() must prefer persisted (non-env) "
        "providers when no env override is set and no provider is named "
        "'default'."
    )


def test_get_default_env_override_still_wins(
    tmp_path, monkeypatch
):
    """$RUFLO_LLM_PROVIDER env var must continue to override everything."""
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    _write_registry(
        cfg_path,
        {
            "openai": _make_config(
                "openai", "openai",
                sourced_from_env=True,
                base_url="https://api.openai.com/v1",
                default_chat_model="gpt-4o-mini",
            ),
            "ollama": _make_config(
                "ollama", "ollama",
                sourced_from_env=False,
                base_url="http://127.0.0.1:11434",
                default_chat_model="qwen3.5-9b-custom",
            ),
        },
    )
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "openai")

    chosen = ProviderRegistry.get_default()
    assert chosen.name == "openai"


def test_get_default_named_default_still_wins(
    tmp_path, monkeypatch
):
    """A provider explicitly named 'default' should still take precedence
    over insertion order (back-compat with the current behaviour)."""
    cfg_path = tmp_path / "llm-providers.json"
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    _write_registry(
        cfg_path,
        {
            "openai": _make_config(
                "openai", "openai",
                sourced_from_env=True,
                base_url="https://api.openai.com/v1",
                default_chat_model="gpt-4o-mini",
            ),
            "default": _make_config(
                "default", "ollama",
                sourced_from_env=False,
                base_url="http://127.0.0.1:11434",
                default_chat_model="qwen3.5-9b-custom",
            ),
        },
    )
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)

    chosen = ProviderRegistry.get_default()
    assert chosen.name == "default"