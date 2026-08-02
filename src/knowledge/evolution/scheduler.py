"""EvolutionScheduler — lightweight periodic trigger for EvolutionLoop.

No external dependencies (no APScheduler/Celery). Uses asyncio.sleep for
periodic checks. State persisted to JSON for restart survival.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from src.knowledge.evolution.loop import EvolutionLoop, EvolutionResult

_logger = logging.getLogger(__name__)


class EvolutionScheduler:
    """Lightweight periodic scheduler for evolution tasks.

    Runs in the background (launched from FastAPI lifespan).
    No external dependencies (no APScheduler/Celery).

    Behavior:
    - Checks every hour whether 24h have passed since last run
    - If >= 23h since last run → triggers evolution cycle
    - Records last run timestamp to .index/curator_last_run.json
    - Manual trigger via CLI resets the timer
    - Survives restarts (reads last run from file)
    """

    CHECK_INTERVAL_SECONDS = 3600       # Check every hour
    MIN_RUN_INTERVAL_SECONDS = 82800    # 23 hours between runs

    def __init__(self, evolution_loop: "EvolutionLoop", wiki_paths) -> None:
        self._loop: "EvolutionLoop" = evolution_loop
        self._state_file: "Path" = wiki_paths.index / "curator_last_run.json"
        self._running: bool = False
        self._task: "asyncio.Task | None" = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def last_run_at(self) -> int:
        """Read last run timestamp from state file. Returns 0 if never run."""
        try:
            if not self._state_file.exists():
                return 0
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return int(data.get("last_run_at", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            return 0

    @property
    def run_count(self) -> int:
        """Read run count from state file. Returns 0 if never run."""
        try:
            if not self._state_file.exists():
                return 0
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return int(data.get("run_count", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            return 0

    @property
    def is_running(self) -> bool:
        """Whether the scheduler background task is active."""
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduling loop.

        Creates an asyncio task that checks periodically.
        Safe to call multiple times (no-op if already running).
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        """Stop the background scheduling loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def trigger_now(self) -> "EvolutionResult":
        """Manual trigger — run evolution cycle immediately, then reset timer.

        Used by CLI: python -m src.cli curate --project <id>
        """
        result = await self._loop.run()
        self._record_run()
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _scheduler_loop(self) -> None:
        """Internal loop: sleep CHECK_INTERVAL_SECONDS, check if due, run if needed."""
        while self._running:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                if not self._running:
                    break
                if self._should_run():
                    await self._loop.run()
                    self._record_run()
            except asyncio.CancelledError:
                break
            except Exception:
                _logger.exception("EvolutionScheduler loop error — continuing")

    def _should_run(self) -> bool:
        """Check if enough time has passed since the last run."""
        last_ms = self.last_run_at
        if last_ms == 0:
            return True
        now_sec = time.time()
        last_sec = last_ms / 1000.0
        elapsed = now_sec - last_sec
        return elapsed >= self.MIN_RUN_INTERVAL_SECONDS

    def _record_run(self) -> None:
        """Write current timestamp and incremented run_count to the state file."""
        now_ms = int(time.time() * 1000)
        data = {
            "last_run_at": now_ms,
            "run_count": self.run_count + 1,
        }
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
