"""Tests for cmd_llm_providers_show using redacted to_dict form.

Plan 19 — Task 10: I-llm-12. The `show` subcommand must mask api_key
(never display the plaintext key) but otherwise reflect the full config.
"""
import argparse
import json

from src.cli_ext.llm_providers_cmd import cmd_llm_providers_show
from src.llm.registry import ProviderRegistry
from src.llm.types import ProviderConfig


def _isolated_registry(monkeypatch, tmp_path):
    """Stub registry config path."""
    from src.llm import registry as reg
    config_dir_path = tmp_path / "config"
    config_dir_path.mkdir()
    monkeypatch.setattr(
        reg, "_config_path", lambda: config_dir_path / "llm-providers.json"
    )
    return reg


def test_show_redacts_api_key(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    cfg = ProviderConfig(
        name="dummy",
        type="openai",
        base_url="https://api.example.com",
        api_key="sk-supersecret-1234567890",
        default_chat_model="gpt-x",
    )
    ProviderRegistry.upsert(cfg)

    args = argparse.Namespace(name="dummy")
    cmd_llm_providers_show(args)

    out = capsys.readouterr().out
    # The full key must not appear anywhere in stdout.
    assert "sk-supersecret-1234567890" not in out
    # The masked form IS printed.
    assert "***" in out
    # Round-trip through JSON to confirm the field is structurally masked.
    parsed = json.loads(out)
    assert parsed["api_key"].startswith("***")
    assert "supersecret" not in parsed["api_key"]


def test_show_preserves_other_fields(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    cfg = ProviderConfig(
        name="dummy",
        type="openai",
        base_url="https://api.example.com",
        api_key="sk-supersecret-1234567890",
        default_chat_model="gpt-x",
    )
    ProviderRegistry.upsert(cfg)

    args = argparse.Namespace(name="dummy")
    cmd_llm_providers_show(args)

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["name"] == "dummy"
    assert parsed["type"] == "openai"
    assert parsed["base_url"] == "https://api.example.com"
    assert parsed["default_chat_model"] == "gpt-x"
