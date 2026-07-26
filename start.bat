@echo off
REM ============================================================
REM  ruflo-kb one-click launcher (Windows)
REM  Usage: double-click this file, or run "start.bat" in a terminal.
REM  Server runs in the foreground; press Ctrl+C to stop it.
REM ============================================================
cd /d "%~dp0"

REM Activate a local venv if one exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Start the HTTP API server (foreground)
python -m src.cli serve --host 127.0.0.1 --port 8765

REM ---- Alternatives (uncomment to use) ----
REM Daemon mode (runs in the background):
REM python -m src.cli serve --host 127.0.0.1 --port 8765 --daemon
REM Stop a daemon:
REM python -m src.cli serve-stop
REM
REM NOTE on searchability:
REM  "python -m src.cli serve" only starts the API. To make the wiki
REM  content semantically searchable you must ALSO run the archive step
REM  (ingest != archive). We already built 141 chunks earlier; you do
REM  not need to re-archive on every launch. Re-archive only when you
REM  ingest new raw sources, e.g.:
REM    python scripts/batch_build.py --only archive --force
