"""Tests for scripts/extract_pilot.py — T1 default-LLM wiring.

The pilot script is intended to be runnable without an explicit
``--provider``: when no provider is configured it should silently fall
back to the heuristic-only path; when the registry / env var is set it
should auto-resolve the configured provider so Stage 1/3/4/5 can take
the LLM fallback path.
"""
import json
from unittest.mock import patch

import pytest


def test_build_llm_returns_none_when_no_provider_configured(monkeypatch, tmp_path):
    """When no providers exist in the registry AND no env var is set,
    _build_llm(None) must return None (heuristic-only path)."""
    from scripts import extract_pilot

    # Empty registry
    cfg_path = tmp_path / "llm-providers.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "src.llm.registry._config_path", lambda: cfg_path
    )
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)

    assert extract_pilot._build_llm(None) is None


def test_build_llm_auto_resolves_default_provider(monkeypatch, tmp_path):
    """When $RUFLO_LLM_PROVIDER points to a configured provider,
    _build_llm(None) must auto-resolve and return an AnthropicLLMClient
    bound to that provider name."""
    from scripts import extract_pilot
    from src.pipeline.v7_extract.llm_client import AnthropicLLMClient

    cfg_path = tmp_path / "llm-providers.json"
    cfg_path.write_text(json.dumps({
        "version": 1,
        "providers": {
            "minimax": {
                "name": "minimax",
                "type": "openai-compatible",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key": "test-key",
                "models": {},
                "default_chat_model": "MiniMax-M3",
                "default_embedding_model": "",
                "timeout_seconds": 60,
                "extra_headers": {},
                "extra_body": {},
            },
        },
        "default": None,
    }), encoding="utf-8")
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "minimax")

    client = extract_pilot._build_llm(None)
    assert isinstance(client, AnthropicLLMClient)
    assert client.provider_name == "minimax"


def test_build_llm_explicit_provider_wins(monkeypatch, tmp_path):
    """When the caller passes an explicit provider_name, _build_llm
    uses it verbatim — even if the env var points elsewhere."""
    from scripts import extract_pilot

    cfg_path = tmp_path / "llm-providers.json"
    cfg_path.write_text(json.dumps({
        "version": 1,
        "providers": {
            "minimax": {
                "name": "minimax",
                "type": "openai-compatible",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key": "test-key",
                "models": {},
                "default_chat_model": "MiniMax-M3",
                "default_embedding_model": "",
                "timeout_seconds": 60,
                "extra_headers": {},
                "extra_body": {},
            },
            "ollama": {
                "name": "ollama",
                "type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "api_key": "",
                "models": {},
                "default_chat_model": "qwen2.5:7b",
                "default_embedding_model": "nomic-embed-text",
                "timeout_seconds": 60,
                "extra_headers": {},
                "extra_body": {},
            },
        },
        "default": None,
    }), encoding="utf-8")
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "minimax")

    client = extract_pilot._build_llm("ollama")
    assert client.provider_name == "ollama"


def test_build_llm_returns_none_on_provider_construction_failure(monkeypatch, tmp_path):
    """If the registry points to a non-existent provider, _build_llm
    must NOT crash the pilot — return None and let it fall back to
    the offline heuristic path."""
    from scripts import extract_pilot

    cfg_path = tmp_path / "llm-providers.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.llm.registry._config_path", lambda: cfg_path)
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "does-not-exist")

    assert extract_pilot._build_llm(None) is None
