"""Tests for quality CLI --config-root argument handling.

Verifies that:
- The `quality config set` subparser accepts `--config-root` (no AttributeError).
- cmd_quality_config_set writes to <config_root>/.index/quality_settings.json
  when --config-root is provided.
- Default behavior (no --config-root) still uses Path.cwd().
"""
import json
import sys

from src.cli_ext.quality_cmd import cmd_quality_config_set


def _build_parser():
    """Build the same parser shape as src/cli.py for `quality config set`."""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("key")
    p.add_argument("value")
    p.add_argument("--config-root", default=None,
                   help="Override config root (default: cwd)")
    return p


def test_quality_set_parser_accepts_config_root():
    """The argparse subparser must accept --config-root without errors."""
    parser = _build_parser()
    args = parser.parse_args(["threshold_pass", "0.85", "--config-root", "/tmp/foo"])
    assert args.key == "threshold_pass"
    assert args.value == "0.85"
    assert args.config_root == "/tmp/foo"


def test_quality_set_uses_config_root(tmp_path):
    """cmd_quality_config_set writes to <config_root>/.index/quality_settings.json."""
    config_root = tmp_path / "custom_root"
    args = type("A", (), {"key": "threshold_pass", "value": "0.85", "config_root": str(config_root)})()
    cmd_quality_config_set(args)
    cfg = config_root / ".index" / "quality_settings.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["threshold_pass"] == 0.85


def test_quality_set_falls_back_to_cwd(tmp_path, monkeypatch):
    """Without --config-root, config is written to cwd/.index/quality_settings.json."""
    monkeypatch.chdir(tmp_path)
    args = type("A", (), {"key": "threshold_pass", "value": "0.7", "config_root": None})()
    cmd_quality_config_set(args)
    cfg = tmp_path / ".index" / "quality_settings.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["threshold_pass"] == 0.7


def test_cli_main_parser_has_quality_config_root(monkeypatch):
    """End-to-end: src.cli main() parses `quality config set --config-root <path>`."""
    # Patch main() exit side-effect: only verify argparse, don't run the command.
    import src.cli as cli_mod

    captured = {}

    def fake_func(args):
        captured["args"] = args

    # Patch the command function on the module so we don't write to disk.
    monkeypatch.setattr(cli_mod, "cmd_quality_config_set", fake_func)

    test_argv = [
        "src.cli", "quality", "config", "set",
        "threshold_pass", "0.85", "--config-root", "/tmp/x",
    ]
    monkeypatch.setattr(sys, "argv", test_argv)
    cli_mod.main()

    assert "args" in captured, "cmd_quality_config_set was not invoked"
    a = captured["args"]
    assert a.config_root == "/tmp/x"
    assert a.key == "threshold_pass"
    assert a.value == "0.85"
