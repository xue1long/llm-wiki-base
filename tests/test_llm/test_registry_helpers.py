"""Tests for ProviderRegistry.require() and get_default() helpers.

These helpers centralise the two patterns duplicated across 8+ caller
files: 'look up by name or fail with a CLI-friendly message' and
'get the default provider or the first available one'.
"""
import pytest

from src.llm.registry import ProviderNotFoundError, ProviderRegistry


def _isolated_registry(monkeypatch, tmp_path):
    """Redirect GlobalRegistryStore to a fresh tmp dir."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    return cfg


def test_require_returns_existing_provider(monkeypatch, tmp_path):
    """require() returns the ProviderConfig when name exists."""
    _isolated_registry(monkeypatch, tmp_path)
    ProviderRegistry.upsert(_make_cfg("openai", "openai"))

    cfg = ProviderRegistry.require("openai")
    assert cfg.name == "openai"


def test_require_raises_provider_not_found(monkeypatch, tmp_path):
    """require() raises ProviderNotFoundError with a CLI-friendly message."""
    _isolated_registry(monkeypatch, tmp_path)

    with pytest.raises(ProviderNotFoundError) as exc_info:
        ProviderRegistry.require("nonexistent")
    assert "nonexistent" in str(exc_info.value)
    assert "llm-providers add" in str(exc_info.value)


def test_require_provider_not_found_is_keyerror(monkeypatch, tmp_path):
    """ProviderNotFoundError subclasses KeyError for backward compat.

    Code that does `except KeyError` (the old `get()` behaviour) still
    catches the new exception transparently.
    """
    _isolated_registry(monkeypatch, tmp_path)

    with pytest.raises(KeyError):
        ProviderRegistry.require("does-not-exist")


def test_get_default_returns_named_default(monkeypatch, tmp_path):
    """If a provider named 'default' exists, return it."""
    _isolated_registry(monkeypatch, tmp_path)
    ProviderRegistry.upsert(_make_cfg("openai", "openai"))
    ProviderRegistry.upsert(_make_cfg("default", "openai", model="gpt-4"))

    cfg = ProviderRegistry.get_default()
    assert cfg.name == "default"
    assert cfg.default_chat_model == "gpt-4"


def test_get_default_returns_first_when_no_default(monkeypatch, tmp_path):
    """Without a 'default' provider, get_default returns the first one."""
    _isolated_registry(monkeypatch, tmp_path)
    ProviderRegistry.upsert(_make_cfg("openai", "openai"))
    ProviderRegistry.upsert(_make_cfg("anthropic", "anthropic"))

    cfg = ProviderRegistry.get_default()
    # Insertion order is preserved in modern Python dicts
    assert cfg.name == "openai"


def test_get_default_raises_when_empty(monkeypatch, tmp_path):
    """get_default raises ProviderNotFoundError if no providers configured.

    The registry normally falls back to _default_providers() (3 built-in
    providers) when the config file is missing, so we mock load() to
    return an empty dict to simulate the no-providers state.
    """
    monkeypatch.setattr(ProviderRegistry, "load", staticmethod(lambda: {}))

    with pytest.raises(ProviderNotFoundError):
        ProviderRegistry.get_default()


def _make_cfg(name: str, ptype: str, model: str = "default-model") -> "ProviderConfig":  # noqa: F821
    from src.llm.types import ProviderConfig
    return ProviderConfig(
        name=name,
        type=ptype,
        base_url="http://localhost",
        default_chat_model=model,
    )
