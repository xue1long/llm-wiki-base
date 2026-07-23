"""Tests that ProviderRegistry.save() honours the global safe_write hook.

Plan 20 (followup-carryovers) binding constraint: every file write
through ``src.lib.write_hooks.safe_write`` — never raw
``Path.write_text`` / ``os.unlink``. This guards against torn writes
during concurrent reads and makes saves honour ``AtomicContext``
suspension semantics.

Background: ``ProviderRegistry.save()`` (src/llm/registry.py) writes
the JSON file at ``~/.config/ruflo-kb/llm-providers.json``. Before the
fix it called ``path.write_text(json.dumps(...))`` directly. After the
fix it routes through ``safe_write`` (which uses ``*.tmp`` +
``os.replace`` when not suspended).

These tests assert the new behaviour:
  * ``safe_write`` is invoked with the registry file path and payload.
  * No raw ``Path.write_text`` call lands on the registry file.
  * The end-to-end save/load round-trip still works (i.e. the swap is
    behaviour-preserving for the happy path).
"""
import json
from pathlib import Path

import pytest

from src.llm.registry import ProviderRegistry
from src.llm.types import ProviderConfig


# ---------------------------------------------------------------------------
# Isolation helpers
# ---------------------------------------------------------------------------

def _isolated_registry(monkeypatch, tmp_path):
    """Point _config_path() at a tmp file so the test does not touch the real registry."""
    from src.llm import registry as reg

    config_dir_path = tmp_path / "config"
    config_dir_path.mkdir()
    target = config_dir_path / "llm-providers.json"
    monkeypatch.setattr(reg, "_config_path", lambda: target)
    return target


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_save_calls_safe_write(monkeypatch, tmp_path):
    """Registry.save() must route the write through safe_write.

    Wrapping safe_write with a spy lets us assert that:
      - save() invokes safe_write at all (i.e. uses the global hook),
      - the path passed in is the configured registry path,
      - the content is the JSON dump of the providers dict.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Spy on safe_write by patching it in the namespace where registry
    # imported it. We patch src.lib.write_hooks.safe_write so any caller
    # that does `from ..lib.write_hooks import safe_write` will see the
    # spy (Python binds the name at import time, so we patch the
    # attribute on the source module instead).
    from src.lib import write_hooks
    captured = []
    real_safe_write = write_hooks.safe_write

    def spy_safe_write(path, content):
        captured.append((Path(path), content))
        return real_safe_write(path, content)

    monkeypatch.setattr(write_hooks, "safe_write", spy_safe_write)

    # Also rebind in the registry module in case it has cached the
    # reference (it does — `from ..lib.write_hooks import safe_write`
    # binds the name into registry.__dict__).
    from src.llm import registry as reg
    monkeypatch.setattr(reg, "safe_write", spy_safe_write)

    cfg = ProviderConfig(
        name="ollama",
        type="ollama",
        base_url="http://example:11434",
        default_chat_model="m",
    )
    ProviderRegistry.save({cfg.name: cfg})

    assert captured, "ProviderRegistry.save() did not call safe_write"
    # The captured path must match the configured registry file (resolved
    # to a Path object — safe_write always normalises to Path).
    paths = [p.resolve() for p, _ in captured]
    assert target.resolve() in paths, (
        f"safe_write called with {paths}; expected {target.resolve()}"
    )

    # At least one captured write should contain the JSON payload for
    # our saved config (we don't know if there are other writes from
    # inner helpers, but the registry save payload must be one of them).
    payloads = [c for _, c in captured]
    assert any("ollama" in p and "m" in p for p in payloads), (
        "safe_write payload did not include the saved providers JSON"
    )


def test_save_does_not_call_raw_path_write_text(monkeypatch, tmp_path):
    """The pre-fix bug: Registry.save() used path.write_text(json.dumps(...)).

    This test pins the fix in place by failing if any code path inside
    Registry.save() ends up calling Path.write_text on the registry
    file. Concretely:
      - We monkeypatch Path.write_text globally to record every call.
      - We save a providers dict.
      - We assert no recorded call touched the registry file.

    Before the fix this test would FAIL (raw path.write_text on the
    registry path is exactly the bug). After the fix it passes because
    the registry path is now written via safe_write (which uses an
    intermediate ``<path>.tmp`` and then ``os.replace``).
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Wrap Path.write_text to record every call site. Wrapping the
    # method on the Path class lets us see calls made via either
    # ``path.write_text(...)`` or ``Path(...).write_text(...)``.
    raw_write_calls = []
    original_write_text = Path.write_text

    def spy_write_text(self, *args, **kwargs):
        raw_write_calls.append(Path(self))
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)

    cfg = ProviderConfig(
        name="ollama",
        type="ollama",
        base_url="http://example:11434",
        default_chat_model="m",
    )
    ProviderRegistry.save({cfg.name: cfg})

    # Filter to writes that landed on the registry path itself (the
    # safe_write implementation writes to <path>.tmp + os.replace, so
    # those intermediate writes are EXPECTED — we only forbid raw
    # write_text on the registry path).
    registry_target = target.resolve()
    offending = [
        p for p in raw_write_calls
        if p.resolve() == registry_target
    ]
    assert not offending, (
        "ProviderRegistry.save() wrote the registry file via raw "
        f"Path.write_text; offending calls: {offending}. Use "
        "src.lib.write_hooks.safe_write instead."
    )


def test_save_round_trip_after_safe_write_swap(monkeypatch, tmp_path):
    """The safe_write swap must not regress the save→load behaviour.

    This is a black-box sanity check: after the fix, save() then load()
    must return the same providers (modulo the env-key strip in save).
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = ProviderConfig(
        name="local",
        type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="qwen2.5:7b",
    )
    ProviderRegistry.save({cfg.name: cfg})

    # File must exist and be valid JSON.
    assert target.exists()
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert "local" in raw["providers"]

    # Round-trip through load().
    loaded = ProviderRegistry.load()
    assert "local" in loaded
    assert loaded["local"].type == "ollama"
    assert loaded["local"].default_chat_model == "qwen2.5:7b"


def test_safe_write_accepts_path_object(monkeypatch, tmp_path):
    """safe_write must accept Path objects (registry passes Path).

    Belt-and-braces: the registry's _config_path() returns a Path; the
    save() call passes it straight through to safe_write. Verify the
    happy path works without coercing to str.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from src.lib import write_hooks

    cfg = ProviderConfig(
        name="local",
        type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="m",
    )
    # Must not raise — this is the regression guard for the type contract.
    write_hooks.safe_write(target, "sentinel-content")
    assert target.read_text(encoding="utf-8") == "sentinel-content"


def test_save_uses_atomic_replace_pattern(monkeypatch, tmp_path):
    """safe_write must use the *.tmp + os.replace atomic pattern.

    This is the regression that motivates the fix in the first place:
    a crash mid-write to a raw Path.write_text leaves the registry
    file torn. After the fix the write is staged via a sibling
    ``.tmp`` file and renamed atomically.

    We assert the side-effects: the final path exists, and no leftover
    ``.tmp`` file remains in the same directory.
    """
    target = _isolated_registry(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = ProviderConfig(
        name="local",
        type="ollama",
        base_url="http://localhost:11434",
        default_chat_model="m",
    )
    ProviderRegistry.save({cfg.name: cfg})

    assert target.exists()
    tmp_sibling = target.with_name(target.name + ".tmp")
    assert not tmp_sibling.exists(), (
        f"Atomic write left a leftover tmp file: {tmp_sibling}"
    )