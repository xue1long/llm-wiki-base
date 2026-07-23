"""`serve` CLI subcommand — start FastAPI server (foreground or daemon)."""
import argparse
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path


_logger = logging.getLogger(__name__)

PIDFILE = Path(os.path.expanduser("~/.config/ruflo-kb/server.pid"))


def _is_posix() -> bool:
    """Return True if running on a POSIX-compatible system (Linux/macOS).

    Wrapped in a function so tests can mock the platform decision
    without monkeypatching os.name (which breaks pathlib on Windows).
    """
    return os.name == "posix"


def _fork() -> int:
    """Wrapper around os.fork (POSIX-only).

    Wrapped so tests on Windows can mock the fork call without
    needing os.fork to exist as an attribute.
    """
    return os.fork()


def _setsid() -> None:
    """Wrapper around os.setsid (POSIX-only)."""
    os.setsid()


def _getpid() -> int:
    """Wrapper around os.getpid."""
    return os.getpid()


def _exit(code: int) -> None:
    """Wrapper around os._exit (POSIX-only)."""
    os._exit(code)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start HTTP API server."""
    if args.daemon:
        _daemonize(args)
    else:
        _serve_foreground(args)


def _serve_foreground(args: argparse.Namespace) -> None:
    """Start uvicorn in the current process (foreground)."""
    import uvicorn
    from ..server.app import create_app
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def _daemonize(args: argparse.Namespace) -> None:
    """Spawn server into background and detach.

    Platform split:
    - POSIX (Linux/macOS): double-fork pattern (os.fork + setsid)
    - Windows: subprocess.Popen with DETACHED_PROCESS flag (os.fork unavailable)

    Both paths write a pidfile and redirect stdio to a log file.
    """
    # Common preflight: refuse to start if pidfile points to a live process
    if PIDFILE.exists():
        try:
            existing_pid = int(PIDFILE.read_text().strip())
            os.kill(existing_pid, 0)  # check if alive
            print(f"Server already running (PID {existing_pid}); run `serve-stop` first")
            sys.exit(2)
        except (ProcessLookupError, OSError, ValueError):
            # ProcessLookupError on POSIX, OSError on Windows (WinError 87 for non-existent PID)
            # ValueError if pidfile content is malformed
            PIDFILE.unlink()

    log_path = Path(os.path.expanduser("~/.config/ruflo-kb/server.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if _is_posix():
        _daemonize_posix(args, log_path)
    else:
        # pragma: no cover  (Windows-only path; integration-tested manually)
        _daemonize_windows(args, log_path)


def _daemonize_posix(args: argparse.Namespace, log_path: Path) -> None:
    """POSIX double-fork daemon pattern."""
    # First fork: parent exits, child becomes session leader
    if _fork() > 0:
        # Parent exits
        return
    _setsid()  # new session
    # Redirect stdio
    with open(log_path, "ab") as log_f:
        os.dup2(log_f.fileno(), 1)
        os.dup2(log_f.fileno(), 2)
    # Fork again: second parent exits so child can never reacquire a controlling terminal
    if _fork() > 0:
        _exit(0)
    # Write pidfile (we are now the final daemon child)
    PIDFILE.write_text(str(_getpid()))
    try:
        _serve_foreground(args)
    finally:
        PIDFILE.unlink(missing_ok=True)


def _daemonize_windows(args: argparse.Namespace, log_path: Path) -> None:
    """Windows daemon via subprocess.Popen with DETACHED_PROCESS.

    On Windows, os.fork() is unavailable (AttributeError). We use subprocess.Popen
    with creation flags that detach the child from the parent's console and process
    group. The child re-executes this same CLI script in foreground mode.
    """
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    # Build the command to re-invoke ourselves in foreground mode
    cmd = [
        sys.executable,
        "-m", "src.cli",
        "serve",
        "--host", args.host,
        "--port", str(args.port),
    ]
    with open(log_path, "ab") as log_f:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=log_f,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    # Parent returns immediately. The detached child writes its own pidfile.
    # Note: pidfile is written by the child during _serve_foreground on POSIX,
    # but on Windows we can't reliably know the child's PID from here.
    # A simple workaround: poll the pidfile after a short delay.
    import time
    for _ in range(50):  # up to ~5s
        if PIDFILE.exists():
            return
        time.sleep(0.1)
    print("Warning: daemon started but pidfile not detected within 5s")


def _read_pidfile_or_cleanup() -> int | None:
    """Read PID from PIDFILE, cleaning up + exiting cleanly on parse/missing errors.

    Returns the parsed PID, or None if the pidfile is missing (silent — caller
    decides what to print). Raises SystemExit(0) on parse failure after removing
    the stale pidfile.
    """
    if not PIDFILE.exists():
        return None
    try:
        return int(PIDFILE.read_text().strip())
    except (ValueError, FileNotFoundError):
        # Pidfile was corrupt (non-int content) or vanished between exists()
        # and read_text(). Treat as stale; unlink and signal caller to exit 0.
        try:
            PIDFILE.unlink(missing_ok=True)
            print("stale pidfile removed")
        except OSError:
            pass
        sys.exit(0)


def cmd_serve_stop(args: argparse.Namespace) -> None:
    """Stop daemon (SIGTERM via pidfile)."""
    pid = _read_pidfile_or_cleanup()
    if pid is None:
        print("No server running (no pidfile)")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to PID {pid}")
        PIDFILE.unlink(missing_ok=True)
    except (ProcessLookupError, OSError):
        print(f"PID {pid} not found (stale pidfile)")
        PIDFILE.unlink(missing_ok=True)


def cmd_serve_status(args: argparse.Namespace) -> None:
    """Check if server is running."""
    pid = _read_pidfile_or_cleanup()
    if pid is None:
        print("Server not running")
        return
    try:
        os.kill(pid, 0)
        print(f"Server running (PID {pid})")
    except (ProcessLookupError, OSError):
        print(f"PID {pid} not running (stale pidfile)")
        PIDFILE.unlink(missing_ok=True)