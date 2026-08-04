"""Background worker pool for continuous task processing.

Provides persistent workers that poll the queue and dispatch tasks,
eliminating idle gaps between task completion and the next dispatch.

Configuration:
    RUFLO_WORKER_COUNT: Number of workers (default: 4)
    RUFLO_WORKER_POLL_INTERVAL: Poll interval in seconds (default: 0.5)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..queue.service import QueueService

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_WORKER_COUNT = 4
DEFAULT_POLL_INTERVAL = 0.5


class WorkerPool:
    """Continuous background workers for queue processing.

    Each worker polls the queue and dispatches tasks via advance().
    When the queue is empty or circuit breaker is open, workers sleep
    briefly before retrying.

    Example:
        pool = WorkerPool(queue_service, num_workers=4)
        await pool.start()

        # ... on shutdown ...
        await pool.stop()
    """

    def __init__(
        self,
        queue_service: "QueueService",
        num_workers: int | None = None,
        poll_interval: float | None = None,
    ):
        self.queue = queue_service
        self.num_workers = num_workers or int(
            os.environ.get("RUFLO_WORKER_COUNT", str(DEFAULT_WORKER_COUNT))
        )
        self.poll_interval = poll_interval or float(
            os.environ.get("RUFLO_WORKER_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL))
        )
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start all workers.

        Workers begin polling immediately. Safe to call multiple times
        (idempotent - only starts once).
        """
        if self._running:
            logger.warning("[WorkerPool] Already running, skipping start")
            return

        self._running = True
        self._stop_event.clear()

        for i in range(self.num_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

        logger.info(
            f"[WorkerPool] Started {self.num_workers} workers "
            f"(poll_interval={self.poll_interval}s)"
        )

    async def stop(self) -> None:
        """Stop all workers gracefully.

        Workers complete their current dispatch before stopping.
        No new tasks are picked up after stop() is called.
        """
        if not self._running:
            return

        logger.info("[WorkerPool] Stopping workers...")
        self._running = False
        self._stop_event.set()

        # Wait for all workers to finish
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

        logger.info("[WorkerPool] All workers stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker main loop: continuously poll and dispatch.

        Flow:
        1. Call queue.advance() to dispatch a task
        2. If dispatched, immediately try again (no sleep)
        3. If not dispatched (empty/circuit open), sleep briefly
        4. Repeat until stop() is called
        """
        logger.debug(f"[Worker {worker_id}] Started")

        while self._running:
            try:
                # Try to dispatch a task
                dispatched = self.queue.advance()

                if dispatched:
                    # Task dispatched, immediately try for more
                    logger.debug(f"[Worker {worker_id}] Dispatched task")
                    continue

                # No task dispatched - queue empty or circuit open
                # Sleep briefly before retrying
                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                # Worker was cancelled - exit gracefully
                logger.debug(f"[Worker {worker_id}] Cancelled")
                break

            except Exception as e:
                # Unexpected error - log and continue
                logger.error(f"[Worker {worker_id}] Error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Longer delay on error

        logger.debug(f"[Worker {worker_id}] Exited")

    @property
    def is_running(self) -> bool:
        """Check if workers are active."""
        return self._running

    @property
    def worker_count(self) -> int:
        """Return the number of workers."""
        return self.num_workers


# Module-level singleton (created on first use)
_default_pool: WorkerPool | None = None


def get_default_worker_pool() -> WorkerPool:
    """Get or create the default worker pool singleton.

    The pool is NOT automatically started. Callers must call start()
    after obtaining the pool (typically during server lifespan).
    """
    global _default_pool
    if _default_pool is None:
        from ..queue.service import get_default_queue_service
        _default_pool = WorkerPool(get_default_queue_service())
    return _default_pool


def reset_worker_pool() -> None:
    """Reset the singleton (for testing)."""
    global _default_pool
    if _default_pool is not None:
        # Stop if running
        if _default_pool.is_running:
            # Note: caller must await stop() in async context
            logger.warning("[WorkerPool] Reset called on running pool")
    _default_pool = None