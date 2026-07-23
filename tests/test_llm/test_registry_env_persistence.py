"""Tests for env-sourced API keys NOT being persisted to disk.

Background (T10 followup): _default_providers() reads OPENAI_API_KEY /
ANTHROPIC_API_KEY from the environment. Before the fix, the first
upsert/save round-trip would write those env-sourced keys to
~/.config/ruflo-kb/llm-providers.json unredacted — even though the
user never explicitly asked the registry to remember them. This is a
security concern: any process with read access to that file (backups,
sync agents, container snapshots) inherits the credential.

The fix: env-sourced ProviderConfig entries carry a runtime-only
sourced_from_env=True hint. Registry.save() excludes those entries
from the JSON, so env vars remain the single source of truth.
Explicit `llm-providers add` (sourced_from_env=False) is still
persisted — that's the intentional ownership boundary.
"""
import json

import pytest

from src.llm.registry import (
    ProviderRegistry,
    _default_providers,
)
from src.llm.types import ProviderConfig


# ---------------------------------------------------------------------------
# Isolation helpers
# ---------------------------------------------------------------------------

def _isolated_registry(monkeypatch, tmp_path):
    """Point _config_path() at a tmp file so the test does not touch the real registry.

    Returns the path to the (eventually-written) JSON file.
    """
    from src.llm import registry as reg

    config_dir_path = tmp_path / "config"
    config_dir_path.mkdir()
    target = config_dir_path / "llm-providers.json"
    monkeypatch.setattr(reg, "_config_path", lambda: target)
    return target


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_env_sourced_key_not_persisted_on_first_save(monkeypatch, tmp_path):
    """OPENAI_API_KEY from env must NOT appear in the persisted JSON.

    Scenario: a user runs the app with OPENAI_API_KEY set but has
    never executed `llm-providers add`. The defaults materialise the
    openai provider from env; the first save must NOT leak the key.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-persist")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = _default_providers()
    ProviderRegistry.save(providers)

    # File should not contain the literal env-sourced key.
    raw = target.read_text(encoding="utf-8")
    assert "test-key-do-not-persist" not in raw, (
        "Env-sourced OPENAI_API_KEY was persisted to the registry JSON. "
        "This is a security regression — env keys must never be written to disk."
    )

    # The loaded-on-disk providers dict should NOT contain the openai
    # entry (since it was the only env-sourced one).
    loaded = ProviderRegistry.load()
    assert "openai" not in loaded, (
        "Env-sourced 'openai' provider was persisted to disk; expected it to be skipped."
    )


def test_env_sourced_anthropic_key_not_persisted(monkeypatch, tmp_path):
    """ANTHROPIC_API_KEY from env is also skipped on save."""
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthro-secret-12345")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    providers = _default_providers()
    ProviderRegistry.save(providers)

    raw = target.read_text(encoding="utf-8")
    assert "anthro-secret-12345" not in raw
    loaded = ProviderRegistry.load()
    assert "anthropic" not in loaded


def test_ollama_default_persists_normally(monkeypatch, tmp_path):
    """Ollama default has no env-sourced key — it must persist normally.

    Sanity check that the persistence filter doesn't accidentally drop
    every default. Only env-sourced entries (those reading
    OPENAI_API_KEY / ANTHROPIC_API_KEY from os.environ) are filtered.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = _default_providers()
    ProviderRegistry.save(providers)

    raw = json.loads(target.read_text(encoding="utf-8"))
    assert "ollama" in raw["providers"], (
        "Ollama is not env-sourced; it MUST persist."
    )
    assert "openai" not in raw["providers"], (
        "openai without env vars: empty key — should not persist."
    )


def test_explicit_add_persists_key(monkeypatch, tmp_path):
    """A user-sourced ProviderConfig (sourced_from_env=False) IS persisted.

    This is the intentional behaviour: when the user runs
    `llm-providers add openai --key ...`, they're explicitly opting in
    to disk persistence. The filter only excludes implicit env-sourced
    entries.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = ProviderConfig(
        name="openai",
        type="openai",
        base_url="https://api.openai.com/v1",
        api_key="user-supplied-explicit-key",
        default_chat_model="gpt-4o-mini",
        default_embedding_model="text-embedding-3-small",
        # sourced_from_env defaults to False
    )
    ProviderRegistry.save({cfg.name: cfg})

    raw = target.read_text(encoding="utf-8")
    assert "user-supplied-explicit-key" in raw
    loaded = ProviderRegistry.load()
    assert loaded["openai"].api_key == "user-supplied-explicit-key"


def test_env_sourced_key_usable_at_runtime(monkeypatch, tmp_path):
    """Env-sourced key is still available via load() (runtime, not disk).

    Critical: the provider must still WORK with the env-sourced key.
    The fix only prevents disk persistence; in-memory materialisation
    from env must continue to work so users don't have to re-add the
    provider every restart.
    """
    _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "live-runtime-key-xyz")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    providers = ProviderRegistry.load()
    assert providers["openai"].api_key == "live-runtime-key-xyz", (
        "Runtime materialisation of env-sourced OPENAI_API_KEY broke. "
        "The fix must only suppress disk persistence, not in-memory access."
    )


def test_sourced_from_env_flag_is_runtime_only(monkeypatch, tmp_path):
    """sourced_from_env is a runtime hint; never appears in JSON.

    The field must NOT be part of the on-disk representation (no
    serialise/deserialise round-trip). Otherwise users with old
    registries would see weird behaviour, and we'd accidentally
    leak metadata about env-var sourcing onto disk.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "rt-only-hint-check")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = _default_providers()["openai"]
    assert cfg.sourced_from_env is True

    d = cfg.to_dict()
    assert "sourced_from_env" not in d, (
        "sourced_from_env must NOT appear in to_dict() output — runtime hint only."
    )

    # And from_dict must NOT require / set the field either (back-compat).
    cfg2 = ProviderConfig.from_dict(d)
    assert not hasattr(cfg2, "sourced_from_env") or cfg2.sourced_from_env is False


def test_upsert_env_sourced_provider_does_not_persist(monkeypatch, tmp_path):
    """upsert() of an env-sourced ProviderConfig also skips persistence.

    Belt-and-braces: even if a caller manually constructs a
    sourced_from_env=True ProviderConfig and hands it to upsert(), the
    save filter must strip it. (Defence in depth — the default path
    only matters, but if a downstream caller ever decides to "re-save
    the defaults", they shouldn't accidentally leak keys.)
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = ProviderConfig(
        name="openai",
        type="openai",
        api_key="env-leak-attempt",
        sourced_from_env=True,
    )
    ProviderRegistry.upsert(cfg)

    raw = target.read_text(encoding="utf-8")
    assert "env-leak-attempt" not in raw, (
        "upsert() of a sourced_from_env=True config leaked the key to disk."
    )