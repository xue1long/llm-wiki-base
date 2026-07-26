@echo off
REM ============================================================
REM  ruflo-kb ALL-IN-ONE launcher (Windows)
REM  Step 1: archive wiki notes -> LanceDB vector store
REM  Step 2: start the HTTP API server (foreground)
REM  Usage: double-click, or run "start-full.bat" in a terminal.
REM  Press Ctrl+C to stop the server.
REM ============================================================
cd /d "%~dp0"

REM Activate a local venv if one exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo [1/2] Archiving wiki notes into the vector store (already-archived, unchanged notes are skipped)...
python scripts/batch_build.py --root . --only archive
if errorlevel 1 (
    echo [WARN] archive stage reported failures; the server will still start, but some content may be missing from the vector store.
)

echo [2/2] Starting HTTP API server (foreground; press Ctrl+C to stop)...
start "" http://127.0.0.1:8765/
python -m src.cli serve --host 127.0.0.1 --port 8765

REM Notes:
REM  * The archive step is offline and idempotent: it calls
REM    scripts/batch_build.py which does init_embedding() +
REM    init_vector_store_for_paths() itself, so it does NOT need
REM    the server running. Already-archived, unchanged notes are
REM    skipped automatically (state in .index/batch_build_state.json).
REM  * To force a full rebuild of the vector store, change the
REM    archive line to:  python scripts/batch_build.py --root . --only archive --force
REM  * After this script exits (or after Ctrl+C), the vector store
REM    remains on disk under .index/lancedb and is reused next launch.
