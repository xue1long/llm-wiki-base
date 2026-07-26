#!/usr/bin/env bash
# ============================================================
#  ruflo-kb ALL-IN-ONE launcher (Git Bash / WSL / macOS)
#  Step 1: archive wiki notes -> LanceDB vector store
#  Step 2: start the HTTP API server (foreground)
#  Usage:  ./start-full.sh   (from the repo root; Ctrl+C to stop)
# ============================================================
set -e
cd "$(dirname "$0")"

# Activate a local venv if one exists
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

echo "[1/2] Archiving wiki notes into the vector store (already-archived, unchanged notes are skipped)..."
python scripts/batch_build.py --root . --only archive || echo "[WARN] archive stage reported failures; the server will still start, but some content may be missing from the vector store."

echo "[2/2] Starting HTTP API server (foreground; press Ctrl+C to stop)..."
exec python -m src.cli serve --host 127.0.0.1 --port 8765

# Notes:
#  * The archive step is offline and idempotent: scripts/batch_build.py
#    does init_embedding() + init_vector_store_for_paths() itself, so it
#    does NOT need the server running. Already-archived, unchanged notes
#    are skipped automatically (state in .index/batch_build_state.json).
#  * To force a full rebuild of the vector store, change the archive line to:
#      python scripts/batch_build.py --root . --only archive --force
#  * After this script exits (or after Ctrl+C), the vector store remains
#    on disk under .index/lancedb and is reused next launch.
