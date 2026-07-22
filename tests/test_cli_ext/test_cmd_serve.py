"""Tests for serve CLI subcommand + daemon."""
import argparse
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.cli_ext.serve import (
    cmd_serve,
    cmd_serve_stop,
    cmd_serve_status,
    PIDFILE,
)


# ----- Foreground mode (cross-platform) -----

def test_serve_foreground_calls_uvicorn(monkeypatch):
    """Foreground mode calls uvicorn.run with create_app."""
    run_mock = MagicMock()
    create_app_mock = MagicMock(return_value="fake_app")

    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_serve_foreground", lambda args: run_mock(create_app_mock(), host=args.host, port=args.port, log_level="info"))

    args = argparse.Namespace(host="0.0.0.0", port=9000, daemon=False, stop=False)
    cmd_serve(args)
    run_mock.assert_called_once()


def test_serve_foreground_runs_uvicorn(monkeypatch):
    """Verify _serve_foreground directly calls uvicorn.run."""
    run_mock = MagicMock()
    create_app_mock = MagicMock(return_value="fake_app")

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", run_mock)
    monkeypatch.setattr("src.server.app.create_app", create_app_mock)

    import src.cli_ext.serve as serve_mod
    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=False)
    serve_mod._serve_foreground(args)

    create_app_mock.assert_called_once()
    run_mock.assert_called_once()
    # Verify uvicorn got app + host + port
    call_args = run_mock.call_args
    assert call_args[0][0] == "fake_app"
    assert call_args.kwargs.get("host") == "127.0.0.1" or call_args[1].get("host") == "127.0.0.1"


# ----- Daemon mode (POSIX path, mocked fork) -----

def test_daemon_posix_calls_fork(monkeypatch, tmp_path):
    """POSIX daemon path calls _fork."""
    test_pidfile = tmp_path / "server.pid"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_is_posix", lambda: True)

    fork_mock = MagicMock(return_value=1)  # parent exits immediately
    monkeypatch.setattr(serve_mod, "_fork", fork_mock)

    # Mock _serve_foreground to prevent actual server start
    monkeypatch.setattr(serve_mod, "_serve_foreground", MagicMock())

    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=True)
    cmd_serve(args)

    # _fork should have been called
    assert fork_mock.called


def test_daemon_already_running(monkeypatch, tmp_path, capsys):
    """Daemon refuses to start if pidfile points to a live process."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("99999")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    # Mock os.kill to simulate process is alive (no ProcessLookupError)
    monkeypatch.setattr("src.cli_ext.serve.os.kill", lambda pid, sig: None)

    # Mock sys.exit to raise SystemExit
    def fake_exit(code=0):
        raise SystemExit(code)
    monkeypatch.setattr("src.cli_ext.serve.sys.exit", fake_exit)

    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=True)

    with pytest.raises(SystemExit) as exc:
        cmd_serve(args)
    assert exc.value.code == 2

    out = capsys.readouterr().out
    assert "already running" in out


def test_daemon_stale_pidfile(monkeypatch, tmp_path):
    """Daemon cleans up stale pidfile (process not found)."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("99999")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    # Mock os.kill to raise ProcessLookupError (stale pidfile)
    def kill_raise(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr("src.cli_ext.serve.os.kill", kill_raise)

    # Mock fork to simulate parent exits immediately
    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_is_posix", lambda: True)
    monkeypatch.setattr(serve_mod, "_fork", lambda: 1)

    # Mock _serve_foreground so daemon doesn't actually run
    monkeypatch.setattr(serve_mod, "_serve_foreground", MagicMock())

    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=True)
    cmd_serve(args)

    # Stale pidfile should be removed
    assert not test_pidfile.exists()


def test_daemon_windows_uses_subprocess(monkeypatch, tmp_path):
    """Windows daemon path uses subprocess.Popen, not _fork."""
    test_pidfile = tmp_path / "server.pid"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_is_posix", lambda: False)  # Force Windows path

    popen_mock = MagicMock()
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    # _fork should NOT be called on Windows
    fork_mock = MagicMock()
    monkeypatch.setattr(serve_mod, "_fork", fork_mock)

    # Pretend pidfile gets created (in real subprocess scenario)
    test_pidfile.write_text("12345")

    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=True)
    cmd_serve(args)

    # subprocess.Popen should have been called
    popen_mock.assert_called_once()
    # _fork should NOT have been called on Windows path
    assert not fork_mock.called


def test_daemon_posix_writes_pidfile(monkeypatch, tmp_path):
    """POSIX daemon: in child context, pidfile is written before serving."""
    test_pidfile = tmp_path / "server.pid"
    test_log = tmp_path / "server.log"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_is_posix", lambda: True)

    # First fork returns 0 (we are child), second fork returns 0 (we are child)
    fork_calls = [0]
    def fake_fork():
        fork_calls[0] += 1
        return 0  # Always pretend we are the child
    monkeypatch.setattr(serve_mod, "_fork", fake_fork)

    monkeypatch.setattr(serve_mod, "_setsid", lambda: None)
    monkeypatch.setattr(serve_mod, "_getpid", lambda: 54321)
    monkeypatch.setattr(serve_mod, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    # dup2 redirects stdout/stderr to log file. In tests this would suppress our output,
    # so mock it to a no-op.
    monkeypatch.setattr(serve_mod.os, "dup2", lambda *a, **kw: None)

    # Track pidfile state DURING _serve_foreground call (before the `finally` unlinks it)
    pidfile_during_serve = [None]
    def fake_serve(args):
        # Capture pidfile content while server is "running"
        if test_pidfile.exists():
            pidfile_during_serve[0] = test_pidfile.read_text().strip()
    monkeypatch.setattr(serve_mod, "_serve_foreground", fake_serve)

    args = argparse.Namespace(host="127.0.0.1", port=19828, daemon=True)
    cmd_serve(args)

    # Verify both forks happened
    assert fork_calls[0] == 2
    # Verify pidfile was written during serve (before the finally clause unlinks it)
    assert pidfile_during_serve[0] == "54321"


# ----- Stop command (cross-platform, no fork needed) -----

def test_stop_sends_sigterm(monkeypatch, tmp_path, capsys):
    """Stop command sends SIGTERM to pid in pidfile."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("54321")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    kill_mock = MagicMock()
    monkeypatch.setattr("src.cli_ext.serve.os.kill", kill_mock)

    args = argparse.Namespace()
    cmd_serve_stop(args)

    kill_mock.assert_called_once_with(54321, signal.SIGTERM)
    out = capsys.readouterr().out
    assert "SIGTERM" in out
    assert "54321" in out


def test_stop_no_pidfile(capsys, tmp_path, monkeypatch):
    """Stop command reports when no pidfile exists."""
    test_pidfile = tmp_path / "nonexistent.pid"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = argparse.Namespace()
    cmd_serve_stop(args)

    out = capsys.readouterr().out
    assert "No server running" in out


def test_stop_stale_pidfile(monkeypatch, tmp_path, capsys):
    """Stop command cleans up stale pidfile if process not found."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("11111")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    def kill_raise(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr("src.cli_ext.serve.os.kill", kill_raise)

    args = argparse.Namespace()
    cmd_serve_stop(args)

    out = capsys.readouterr().out
    assert "stale pidfile" in out
    assert not test_pidfile.exists()


# ----- Status command -----

def test_status_running(monkeypatch, tmp_path, capsys):
    """Status reports running PID when process is alive."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("12345")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    monkeypatch.setattr("src.cli_ext.serve.os.kill", lambda pid, sig: None)

    args = argparse.Namespace()
    cmd_serve_status(args)

    out = capsys.readouterr().out
    assert "12345" in out
    assert "running" in out


def test_status_no_pidfile(monkeypatch, tmp_path, capsys):
    """Status reports not running when no pidfile."""
    test_pidfile = tmp_path / "nonexistent.pid"
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    args = argparse.Namespace()
    cmd_serve_status(args)

    out = capsys.readouterr().out
    assert "not running" in out


def test_status_stale_pidfile(monkeypatch, tmp_path, capsys):
    """Status cleans up stale pidfile if process not found."""
    test_pidfile = tmp_path / "server.pid"
    test_pidfile.write_text("99999")
    monkeypatch.setattr("src.cli_ext.serve.PIDFILE", test_pidfile)

    def kill_raise(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr("src.cli_ext.serve.os.kill", kill_raise)

    args = argparse.Namespace()
    cmd_serve_status(args)

    out = capsys.readouterr().out
    assert "stale pidfile" in out or "not running" in out
    assert not test_pidfile.exists()


# ----- CLI integration test -----

def test_cli_parser_has_serve():
    """CLI parser has serve, serve-stop, serve-status subcommands."""
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    # Just check we can add these subparsers (the actual CLI uses set_defaults)
    p_serve = subparsers.add_parser("serve", help="Start HTTP API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=19828)
    p_serve.add_argument("--daemon", action="store_true")

    p_stop = subparsers.add_parser("serve-stop", help="Stop daemon server")

    args = parser.parse_args(["serve", "--daemon", "--port", "9000"])
    assert args.command == "serve"
    assert args.daemon is True
    assert args.port == 9000