"""Tests for ProviderRegistry.get_default() env-var precedence and corrupt-file handling."""
import json

import pytest

from src.llm.registry import (
    ProviderRegistry,
    ProviderNotFoundError,
    RegistryCorruptError,
)


def _isolated_registry(monkeypatch, tmp_path, content=None, register_path=None):
    """Point _config_path() at a tmp file for isolation."""
    from src.llm import registry as reg
    from src.project import paths as project_paths

    cfg = tmp_path / "isolated_cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    target = register_path or (tmp_path / "reg.json")
    monkeypatch.setattr(reg, "_config_path", lambda: target)
    if content is not None:
        target.write_text(content, encoding="utf-8")
    return target


def test_env_var_overrides_named_default(monkeypatch, tmp_path):
    """RUFLO_LLM_PROVIDER env var must override the named 'default' provider."""
    _isolated_registry(monkeypatch, tmp_path, content=json.dumps({
        "providers": {
            "openai": {"name": "openai", "type": "openai", "api_key": "x"},
            "ollama": {"name": "ollama", "type": "ollama", "base_url": "http://x"},
        },
        "default": "openai",
    }))
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "ollama")
    cfg = ProviderRegistry.get_default()
    assert cfg.name == "ollama"


def test_env_var_missing_falls_back_to_named_default(monkeypatch, tmp_path):
    """Without the env var, get_default falls back to a provider NAMED 'default'."""
    _isolated_registry(monkeypatch, tmp_path, content=json.dumps({
        "providers": {
            "openai": {"name": "openai", "type": "openai", "api_key": "x"},
            "default": {"name": "default", "type": "ollama", "base_url": "http://x"},
        },
    }))
    monkeypatch.delenv("RUFLO_LLM_PROVIDER", raising=False)
    cfg = ProviderRegistry.get_default()
    assert cfg.name == "default"


def test_env_var_unknown_provider_raises(monkeypatch, tmp_path):
    """If RUFLO_LLM_PROVIDER names a provider not in the registry, raise ValueError."""
    _isolated_registry(monkeypatch, tmp_path, content=json.dumps({
        "providers": {
            "openai": {"name": "openai", "type": "openai", "api_key": "x"},
        },
    }))
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="RUFLO_LLM_PROVIDER=nope"):
        ProviderRegistry.get_default()


def test_empty_env_var_falls_back(monkeypatch, tmp_path):
    """Empty string in the env must NOT be treated as a valid provider."""
    _isolated_registry(monkeypatch, tmp_path, content=json.dumps({
        "providers": {
            "openai": {"name": "openai", "type": "openai", "api_key": "x"},
        },
        "default": "openai",
    }))
    monkeypatch.setenv("RUFLO_LLM_PROVIDER", "")
    cfg = ProviderRegistry.get_default()
    assert cfg.name == "openai"


def test_load_raises_on_corrupt_existing_file(monkeypatch, tmp_path):
    """If the registry file exists but is invalid JSON, raise RegistryCorruptError."""
    from src.llm import registry as reg

    _isolated_registry(monkeypatch, tmp_path, content="{this is not json")
    with pytest.raises(RegistryCorruptError):
        ProviderRegistry.load()
