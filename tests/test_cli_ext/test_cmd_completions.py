"""Tests for `completions install` and `print-words`."""
import os
from pathlib import Path

from src.cli_ext.completions_cmd import (
    cmd_completions_install,
    cmd_completions_print_words,
    COMPLETION_DIR,
)


def test_completions_install_bash(tmp_path, monkeypatch, capsys):
    """install bash writes ruflo-kb.bash and prints path + bashrc hint."""
    fake_dir = tmp_path / "completions"
    monkeypatch.setattr("src.cli_ext.completions_cmd.COMPLETION_DIR", fake_dir)

    args = type("Args", (), {"shell": "bash"})()
    cmd_completions_install(args)

    out_path = fake_dir / "ruflo-kb.bash"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "complete -F _ruflo_kb_completion" in content
    out = capsys.readouterr().out
    assert "bash" in out.lower()
    assert ".bashrc" in out


def test_completions_install_zsh(tmp_path, monkeypatch, capsys):
    """install zsh writes _ruflo-kb."""
    fake_dir = tmp_path / "completions"
    monkeypatch.setattr("src.cli_ext.completions_cmd.COMPLETION_DIR", fake_dir)

    args = type("Args", (), {"shell": "zsh"})()
    cmd_completions_install(args)

    out_path = fake_dir / "_ruflo-kb"
    assert out_path.exists()
    assert "compdef" in out_path.read_text(encoding="utf-8")


def test_completions_install_fish_print_message(capsys):
    """install fish prints defer message and writes nothing."""
    args = type("Args", (), {"shell": "fish"})()
    cmd_completions_install(args)
    out = capsys.readouterr().out
    assert "deferred" in out.lower() or "v2.0.1" in out


def test_completions_print_words_includes_subcommands(capsys):
    """print-words lists known subcommands."""
    args = type("Args", (), {})()
    cmd_completions_print_words(args)
    out = capsys.readouterr().out
    for sub in ("project", "ingest", "schema", "metrics", "chat"):
        assert sub in out, f"Missing subcommand '{sub}' in print-words output"
