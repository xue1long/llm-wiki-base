"""Tests for quality CLI subcommands (without invoking LLM)."""
import json

from src.cli_ext.quality_cmd import cmd_quality_config_show, cmd_quality_config_set


def test_config_show_prints_defaults(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cmd_quality_config_show(type("A", (), {})())
    out = capsys.readouterr().out
    assert "threshold_pass" in out
    assert "weights" in out


def test_config_set_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = type("A", (), {"key": "threshold_pass", "value": "0.85", "config_root": None})()
    cmd_quality_config_set(args)
    cfg = tmp_path / ".index" / "quality_settings.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["threshold_pass"] == 0.85


def test_config_set_nested_weight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = type("A", (), {"key": "weights.factuality", "value": "0.5", "config_root": None})()
    cmd_quality_config_set(args)
    cfg = tmp_path / ".index" / "quality_settings.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["weights"]["factuality"] == 0.5


def test_config_show_after_set_reflects_value(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    set_args = type("A", (), {"key": "max_retries", "value": "3", "config_root": None})()
    cmd_quality_config_set(set_args)
    cmd_quality_config_show(type("A", (), {})())
    out = capsys.readouterr().out
    assert "max_retries: 3" in out


def test_cmd_quality_score_file_not_found(tmp_path, capsys):
    from src.cli_ext.quality_cmd import cmd_quality_score
    import pytest
    args = type("A", (), {"path": str(tmp_path / "nope.md")})()
    with pytest.raises(SystemExit) as exc:
        cmd_quality_score(args)
    assert exc.value.code == 2
