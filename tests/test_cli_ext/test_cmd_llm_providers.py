"""Tests for llm-providers CLI subcommands."""
from src.cli_ext.llm_providers_cmd import (
    cmd_llm_providers_list,
    cmd_llm_providers_show,
    cmd_llm_providers_remove,
    cmd_llm_providers_set_default,
)


def _isolated_registry(monkeypatch, tmp_path):
    """Stub registry config path."""
    from src.llm import registry as reg
    config_dir_path = tmp_path / "config"
    config_dir_path.mkdir()
    monkeypatch.setattr(
        reg, "_config_path", lambda: config_dir_path / "llm-providers.json"
    )
    return reg


def test_list_prints_default_providers(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    cmd_llm_providers_list(type("A", (), {})())
    out = capsys.readouterr().out
    assert "openai" in out
    assert "ollama" in out


def test_show_unknown_exits_2(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    import pytest
    args = type("A", (), {"name": "nope"})()
    with pytest.raises(SystemExit) as exc:
        cmd_llm_providers_show(args)
    assert exc.value.code == 2


def test_remove_unknown_exits_2(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    import pytest
    args = type("A", (), {"name": "nope"})()
    with pytest.raises(SystemExit) as exc:
        cmd_llm_providers_remove(args)
    assert exc.value.code == 2


def test_set_default_uses_registry_slot_only(capsys, monkeypatch, tmp_path):
    _isolated_registry(monkeypatch, tmp_path)
    args = type("A", (), {"name": "ollama"})()
    cmd_llm_providers_set_default(args)
    from src.llm.registry import ProviderRegistry
    assert ProviderRegistry.get_default_name() == "ollama"
    assert "shell rc" not in capsys.readouterr().out
