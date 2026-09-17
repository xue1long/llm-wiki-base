#!/usr/bin/env bash
# Ponytail: plan 2026-09-18-v7-agl-training.md §10 — soft rollback.
# Stops AGL training without leaving GPU/RAY/vLLM processes behind.

set -euo pipefail

echo "[1/4] Reset llm-providers.json default to v7-default"
python -m src.cli llm-providers set-default v7-default || true

echo "[2/4] SIGTERM agl-controller"
pkill -f agl-controller || true

echo "[3/4] SIGTERM vLLM"
pkill -f "vllm serve" || true

echo "[4/4] SIGTERM agl-server"
pkill -f agl-server || true

echo "Done. AGL training stopped; V7 provider resumed."