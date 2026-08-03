"""Tests for ProviderRegistry aliases and explicit-default support (P2 fix).

Adds:
- list() alias for load()
- get_default_name() reader
- set_default(name) mutator
- Tier 2 in get_default() resolution
"""
import json
from pathlib import Path

import pytest

from src.llm.registry import (
    ProviderNotFoundError,
    ProviderRegistry,
    RUFLO_LLM_PROVIDER_ENV,
    _config_path,
)
from src.llm.types import ProviderConfig


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch):
    """Redirect ProviderRegistry to a tmp config dir; auto-cleanup."""
    from src.project import paths as p_paths
    monkeypatch.setattr(p_paths, "config_dir", lambda: tmp_path)
    # Clear the cached default-name so each test starts clean
    yield tmp_path
    # Don't unlink the file; the test may want to inspect it


def test_list_alias_returns_same_as_load(isolated_registry, monkeypatch) -> None:
    """registry.list() is an alias for load() — same shape, same content."""
    cfg = ProviderConfig(
        name="openai", type="openai",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    ProviderRegistry.upsert(cfg)

    loaded = ProviderRegistry.load()
    listed = ProviderRegistry.list()
    assert loaded == listed
    assert "openai" in listed


def test_set_default_persists_to_disk(isolated_registry) -> None:
    """set_default() writes 'default' key; reload returns it via get_default_name()."""
    cfg = ProviderConfig(
        name="ollama", type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="llama3",
    )
    ProviderRegistry.upsert(cfg)

    ProviderRegistry.set_default("ollama")

    # Reload from disk
    path = _config_path()
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["default"] == "ollama"

    assert ProviderRegistry.get_default_name() == "ollama"


def test_set_default_unknown_raises(isolated_registry) -> None:
    """set_default("nonexistent") raises ProviderNotFoundError."""
    with pytest.raises(ProviderNotFoundError):
        ProviderRegistry.set_default("nonexistent")


def test_get_default_env_overrides_explicit(isolated_registry, monkeypatch) -> None:
    """$RUFLO_LLM_PROVIDER (tier 1) wins over set_default() (tier 2)."""
    ollama = ProviderConfig(
        name="ollama", type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="llama3",
    )
    openai = ProviderConfig(
        name="openai", type="openai",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    ProviderRegistry.upsert(ollama)
    ProviderRegistry.upsert(openai)

    ProviderRegistry.set_default("ollama")
    monkeypatch.setenv(RUFLO_LLM_PROVIDER_ENV, "openai")

    resolved = ProviderRegistry.get_default()
    assert resolved.name == "openai", "env var should override set_default"


def test_get_default_explicit_overrides_named_default_alias(isolated_registry) -> None:
    """set_default('ollama') wins over a provider literally named 'default'."""
    ollama = ProviderConfig(
        name="ollama", type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="llama3",
    )
    default_named = ProviderConfig(
        name="default", type="openai",  # legacy back-compat alias
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    ProviderRegistry.upsert(ollama)
    ProviderRegistry.upsert(default_named)

    ProviderRegistry.set_default("ollama")

    resolved = ProviderRegistry.get_default()
    assert resolved.name == "ollama", (
        "explicit set_default should win over provider named 'default'"
    )


def test_load_old_file_without_default_field(isolated_registry) -> None:
    """Legacy file (no 'default' key) loads with _default_name=None; falls through tiers."""
    # Write a legacy file (no "default" key)
    cfg = ProviderConfig(
        name="openai", type="openai",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    legacy = {
        "version": 1,
        "providers": {cfg.name: cfg.to_dict()},
        # NOTE: no "default" key — legacy format
    }
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy, indent=2), encoding="utf-8")

    # get_default_name() returns None (no key)
    assert ProviderRegistry.get_default_name() is None
    # load() still works
    assert "openai" in ProviderRegistry.load()


def test_save_then_load_roundtrip_preserves_default(isolated_registry) -> None:
    """set_default + load returns the same default name."""
    cfg1 = ProviderConfig(
        name="ollama", type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="llama3",
    )
    cfg2 = ProviderConfig(
        name="openai", type="openai",
        base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
    )
    ProviderRegistry.upsert(cfg1)
    ProviderRegistry.upsert(cfg2)
    ProviderRegistry.set_default("ollama")

    # Force a re-load
    fresh = ProviderRegistry.load()
    assert "ollama" in fresh
    assert "openai" in fresh
    assert ProviderRegistry.get_default_name() == "ollama"
    assert ProviderRegistry.get_default().name == "ollama"
