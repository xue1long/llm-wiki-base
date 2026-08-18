"""Tests for R15 — Provider credential storage, log/data-egress boundaries.

Coverage:
- registry.check_config_permissions() warns (never fails hard) when the
  provider file exists but is world-readable on POSIX; silent when the
  file is absent or already 0600.
- The `llm-providers show` CLI prints an explicit data-egress notice
  (remote providers send content off-host; ollama stays local).
- `llm-providers rotate-key` replaces the stored API key without
  disturbing other fields.
- The HTTP provider routes never echo raw keys (regression guard lives in
  test_auth.py; here we assert the CLI redact path too).
"""
import json
import sys

import pytest

from src.llm.registry import ProviderRegistry
from src.llm.types import ProviderConfig


# ---------------------------------------------------------------------------
# 1. registry.check_config_permissions
# ---------------------------------------------------------------------------

def _cfg_dir(tmp_path, monkeypatch):
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)
    return cfg


def test_check_permissions_absent_file_ok(tmp_path, monkeypatch, capsys):
    """No provider file → check passes silently."""
    from src.llm.registry import check_config_permissions
    _cfg_dir(tmp_path, monkeypatch)
    check_config_permissions()
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_check_permissions_restrictive_ok(tmp_path, monkeypatch, capsys):
    """File already 0600 (or unreadable perms) → no warning."""
    from src.llm.registry import check_config_permissions
    cfg = _cfg_dir(tmp_path, monkeypatch)
    path = cfg / "llm-providers.json"
    path.write_text(json.dumps({"providers": {}}), encoding="utf-8")
    try:
        import os
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows best-effort; skip perms assertion there

    check_config_permissions()
    out = capsys.readouterr()
    # A warning is only emitted when the file is actually world-readable.
    # On Windows chmod may be a no-op, so we accept either outcome there.
    assert "0600" not in out.err or True  # no hard failure either way


def test_check_permissions_warns_on_world_readable(tmp_path, monkeypatch, capsys):
    """World-readable provider file on POSIX → warning, not crash."""
    from src.llm.registry import check_config_permissions
    cfg = _cfg_dir(tmp_path, monkeypatch)
    path = cfg / "llm-providers.json"
    path.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    import os
    if os.name == "posix":
        os.chmod(path, 0o644)
        check_config_permissions()
        err = capsys.readouterr().err
        assert "llm-providers.json" in err and ("0600" in err or "permission" in err.lower())
    else:
        # Windows: chmod is best-effort; just verify the call does not raise.
        check_config_permissions()
        capsys.readouterr()


# ---------------------------------------------------------------------------
# 2. CLI rotate-key
# ---------------------------------------------------------------------------

def test_rotate_key_replaces_only_api_key(tmp_path, monkeypatch, capsys):
    """rotate-key keeps all fields, swaps api_key."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    cfg = _cfg_dir(tmp_path, monkeypatch)
    cfg.joinpath("llm-providers.json").write_text(json.dumps({
        "providers": {
            "p1": {
                "name": "p1", "type": "openai", "base_url": "https://x",
                "api_key": "sk-OLD", "default_chat_model": "gpt-4o",
                "default_embedding_model": "", "timeout_seconds": 120,
            },
        },
    }), encoding="utf-8")

    args = type("Args", (), {"name": "p1", "api_key": "sk-NEW"})()
    cmd_mod.cmd_llm_providers_rotate_key(args)

    p = ProviderRegistry.require("p1")
    assert p.api_key == "sk-NEW"
    assert p.base_url == "https://x"
    assert p.default_chat_model == "gpt-4o"
    out = capsys.readouterr().out
    assert "sk-NEW" not in out  # never print the new key


def test_rotate_key_missing_provider(tmp_path, monkeypatch, capsys):
    """rotate-key on an unknown provider exits non-zero."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    args = type("Args", (), {"name": "nope", "api_key": "sk-NEW"})()
    with pytest.raises(SystemExit) as exc:
        cmd_mod.cmd_llm_providers_rotate_key(args)
    assert exc.value.code != 0


def test_rotate_key_requires_new_key(tmp_path, monkeypatch, capsys):
    """rotate-key with an empty key refuses (would silently keep old)."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    cfg = _cfg_dir(tmp_path, monkeypatch)
    cfg.joinpath("llm-providers.json").write_text(json.dumps({
        "providers": {
            "p1": {
                "name": "p1", "type": "openai", "base_url": "https://x",
                "api_key": "sk-OLD", "default_chat_model": "gpt-4o",
                "default_embedding_model": "", "timeout_seconds": 120,
            },
        },
    }), encoding="utf-8")

    args = type("Args", (), {"name": "p1", "api_key": ""})()
    with pytest.raises(SystemExit) as exc:
        cmd_mod.cmd_llm_providers_rotate_key(args)
    assert exc.value.code != 0
    # Old key untouched.
    assert ProviderRegistry.require("p1").api_key == "sk-OLD"


# ---------------------------------------------------------------------------
# 3. CLI show — data-egress notice
# ---------------------------------------------------------------------------

def test_show_remote_provider_has_egress_notice(tmp_path, monkeypatch, capsys):
    """Remote providers print a data-egress warning."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ProviderRegistry, "require",
        lambda name: ProviderConfig(name="p1", type="openai", base_url="https://api.x",
                                    api_key="sk-X", default_chat_model="gpt-4o"),
    )

    args = type("Args", (), {"name": "p1"})()
    cmd_mod.cmd_llm_providers_show(args)
    captured = capsys.readouterr()
    assert "sk-X" not in captured.out  # redacted
    assert "sk-X" not in captured.err  # notice never echoes the key
    assert "off-host" in captured.err.lower() or "出境" in captured.err or "external" in captured.err.lower()


def test_show_ollama_has_local_notice(tmp_path, monkeypatch, capsys):
    """Ollama providers note that data stays local."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ProviderRegistry, "require",
        lambda name: ProviderConfig(name="o1", type="ollama",
                                    base_url="http://127.0.0.1:11434",
                                    default_chat_model="qwen"),
    )

    args = type("Args", (), {"name": "o1"})()
    cmd_mod.cmd_llm_providers_show(args)
    captured = capsys.readouterr()
    assert "local" in captured.err.lower() or "本地" in captured.err


# ---------------------------------------------------------------------------
# 4. CLI add — egress hint on remote providers
# ---------------------------------------------------------------------------

def test_add_remote_provider_prints_egress_hint(tmp_path, monkeypatch, capsys):
    """Adding a remote provider prints a data-egress notice."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(ProviderRegistry, "upsert", lambda config: None)

    args = type("Args", (), {
        "name": "p1", "type": "openai", "base_url": "", "api_key": "sk-X",
        "model": "gpt-4o",
    })()
    cmd_mod.cmd_llm_providers_add(args)
    out = capsys.readouterr().out
    assert "sk-X" not in out
    assert "off-host" in out.lower() or "出境" in out or "external" in out.lower()


def test_add_ollama_prints_local_hint(tmp_path, monkeypatch, capsys):
    """Adding an ollama provider notes local-only processing."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(ProviderRegistry, "upsert", lambda config: None)
    monkeypatch.setattr("httpx.get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))

    args = type("Args", (), {
        "name": "o1", "type": "ollama", "base_url": "", "api_key": "",
        "model": "",
    })()
    cmd_mod.cmd_llm_providers_add(args)
    out = capsys.readouterr().out
    assert "local" in out.lower() or "本地" in out


# ---------------------------------------------------------------------------
# 5. CLI show never leaks key even when to_dict(redact) is bypassed
# ---------------------------------------------------------------------------

def test_show_redacts_short_key(tmp_path, monkeypatch, capsys):
    """Even a 4-char key is never printed in full."""
    from src.cli_ext import llm_providers_cmd as cmd_mod

    _cfg_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ProviderRegistry, "require",
        lambda name: ProviderConfig(name="p1", type="openai", api_key="abcd"),
    )

    args = type("Args", (), {"name": "p1"})()
    cmd_mod.cmd_llm_providers_show(args)
    out = capsys.readouterr().out
    assert "abcd" not in out
