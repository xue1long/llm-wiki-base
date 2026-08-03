"""dispatch_collector_start — the sync→async bridge for the collector chain.

When enqueue_task emits "collector:start", this handler runs. It detects
whether there's already a running event loop:
- If yes: schedule the chain as a task on that loop.
- If no: drive the chain with asyncio.run (the production sync entry path).

This is the EXACT logic from src/pipeline/pipeline.py:_dispatch_collector_start
(commit 37b644a) — extracted verbatim, no behavior change.
"""
from __future__ import annotations
import asyncio
import logging


_logger = logging.getLogger(__name__)


def dispatch_collector_start(
    pipeline_service, payload: dict,
) -> None:
    """EventBus handler for "collector:start". Bridges sync emit → async chain."""
    coro = pipeline_service.run_for_collector_start(payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop — use asyncio.run (production sync entry path)
        try:
            asyncio.run(coro)
        except Exception:
            _logger.exception("collector chain dispatch failed")
        return
    # Loop exists (test scenario) — schedule
    loop.create_task(coro)
