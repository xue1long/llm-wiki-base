"""Tests for serve CLI: corrupt pidfile is cleaned up cleanly.

Verifies that:
- `cmd_serve_stop` with a malformed pidfile (e.g. "abc" or empty) unlinks the
  pidfile, prints a stderr/stdout message, and exits 0 (or 1) without
  raising an unhandled ValueError.
- `cmd_serve_status` with a malformed pidfile unlinks it and exits cleanly.
"""
import pytest

from src.cli_ext import serve as serve_mod
from src.cli_ext.serve import cmd_serve_stop, cmd_serve_status


def test_stop_corrupt_pidfile_unlinks(monkeypatch, tmp_path, capsys):
    """cmd_serve_stop with non-int content unlinks the pidfile and exits cleanly."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("not-a-pid")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = type("A", (), {})()
    # Should NOT raise; the contract is to clean up + exit 0/1 with message.
    result = None
    try:
        cmd_serve_stop(args)
    except SystemExit as e:
        result = e.code

    assert result in (None, 0, 1)
    assert not test_pidfile.exists()
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    combined = out + err
    # Either "stale pidfile" or "corrupt" or "not a pid" message printed
    assert "stale pidfile" in combined or "corrupt" in combined or "removed" in combined


def test_stop_empty_pidfile_unlinks(monkeypatch, tmp_path, capsys):
    """cmd_serve_stop with an empty pidfile unlinks it cleanly."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = type("A", (), {})()
    try:
        cmd_serve_stop(args)
    except SystemExit:
        pass

    assert not test_pidfile.exists()


def test_status_corrupt_pidfile_unlinks(monkeypatch, tmp_path, capsys):
    """cmd_serve_status with non-int content unlinks the pidfile cleanly."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("garbage\n")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = type("A", (), {})()
    try:
        cmd_serve_status(args)
    except SystemExit:
        pass

    assert not test_pidfile.exists()
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    combined = out + err
    assert "stale pidfile" in combined or "corrupt" in combined or "not running" in combined


def test_status_missing_pidfile_clean(monkeypatch, tmp_path, capsys):
    """cmd_serve_status with a missing pidfile prints 'not running' and exits cleanly."""
    test_pidfile = tmp_path / "nonexistent.pid"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = type("A", (), {})()
    cmd_serve_status(args)

    out = capsys.readouterr().out
    assert "not running" in out
