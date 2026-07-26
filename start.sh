#!/usr/bin/env bash
# ============================================================
#  ruflo-kb one-click launcher (Git Bash / WSL / macOS)
#  Usage:  ./start.sh   (from the repo root)
#  Server runs in the foreground; press Ctrl+C to stop it.
# ============================================================
set -e
cd "$(dirname "$0")"

# Activate a local venv if one exists
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

# Start the HTTP API server (foreground)
exec python -m src.cli serve --host 127.0.0.1 --port 8765

# ---- Alternatives ----
# Daemon mode (runs in the background):
#   python -m src.cli serve --host 127.0.0.1 --port 8765 --daemon
# Stop a daemon:
#   python -m src.cli serve-stop
#
# NOTE: "serve" only starts the API. To make the wiki content
# semantically searchable you must ALSO run the archive step
# (ingest != archive). We already built 141 chunks earlier, so
# you do NOT need to re-archive on every launch. Re-archive only
# after ingesting new raw sources, e.g.:
#   python scripts/batch_build.py --only archive --force
