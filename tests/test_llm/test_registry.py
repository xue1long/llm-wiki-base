"""Tests for ProviderRegistry."""
import json

import pytest

from src.llm.registry import ProviderRegistry, _default_providers
from src.llm.types import ProviderConfig


def _isolated_registry(monkeypatch, tmp_path):
    """Stub config_dir() to a tmpdir so the test does not touch the real registry."""
    from src.llm import registry as reg

    config_dir_path = tmp_path / "config"
    config_dir_path.mkdir()
    # Patch the module-level _config_path() function inside registry.
    monkeypatch.setattr(
        reg, "_config_path", lambda: config_dir_path / "llm-providers.json"
    )
    return reg


def test_load_returns_defaults_when_no_file(monkeypatch, tmp_path):
    reg = _isolated_registry(monkeypatch, tmp_path)
    providers = ProviderRegistry.load()
    assert "ollama" in providers
    assert providers["ollama"].type == "ollama"


def test_upsert_persists(monkeypatch, tmp_path):
    reg = _isolated_registry(monkeypatch, tmp_path)
    cfg = ProviderConfig(
        name="local-x",
        type="ollama",
        base_url="http://example:11434",
        default_chat_model="m",
    )
    ProviderRegistry.upsert(cfg)
    # Read raw file to verify persistence
    raw = json.loads((tmp_path / "config" / "llm-providers.json").read_text())
    assert "local-x" in raw["providers"]
    # And load returns it
    providers = ProviderRegistry.load()
    assert "local-x" in providers


def test_get_not_found(monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    with pytest.raises(KeyError):
        ProviderRegistry.get("does_not_exist")


def test_remove(monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    assert ProviderRegistry.remove("openai") is True
    providers = ProviderRegistry.load()
    assert "openai" not in providers
    # Removing again returns False
    assert ProviderRegistry.remove("openai") is False


def test_default_providers_have_ollama():
    defaults = _default_providers()
    assert "openai" in defaults
    assert "anthropic" in defaults
    assert "ollama" in defaults
