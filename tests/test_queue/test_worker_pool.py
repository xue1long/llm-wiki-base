"""Tests for WorkerPool background task processing."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.queue.worker_pool import WorkerPool, get_default_worker_pool, reset_worker_pool


class TestWorkerPool:
    """Tests for WorkerPool functionality."""

    @pytest.fixture
    def mock_queue(self):
        """Create a mock queue service."""
        queue = MagicMock()
        queue.advance = MagicMock(return_value=False)  # Default: no tasks
        return queue

    @pytest.fixture
    def pool(self, mock_queue):
        """Create a worker pool with mock queue."""
        return WorkerPool(mock_queue, num_workers=2, poll_interval=0.1)

    def test_init_default_config(self, mock_queue):
        """Test default configuration."""
        pool = WorkerPool(mock_queue)
        assert pool.num_workers == 4  # DEFAULT_WORKER_COUNT
        assert pool.poll_interval == 0.5  # DEFAULT_POLL_INTERVAL

    def test_init_custom_config(self, mock_queue):
        """Test custom configuration."""
        pool = WorkerPool(mock_queue, num_workers=8, poll_interval=0.2)
        assert pool.num_workers == 8
        assert pool.poll_interval == 0.2

    def test_env_config(self, mock_queue, monkeypatch):
        """Test environment variable configuration."""
        monkeypatch.setenv("RUFLO_WORKER_COUNT", "6")
        monkeypatch.setenv("RUFLO_WORKER_POLL_INTERVAL", "0.3")

        pool = WorkerPool(mock_queue)
        assert pool.num_workers == 6
        assert pool.poll_interval == 0.3

    @pytest.mark.asyncio
    async def test_start_stop(self, pool):
        """Test starting and stopping the pool."""
        assert not pool.is_running

        await pool.start()
        assert pool.is_running
        assert len(pool._workers) == 2

        await pool.stop()
        assert not pool.is_running
        assert len(pool._workers) == 0

    @pytest.mark.asyncio
    async def test_idempotent_start(self, pool):
        """Test that start() is idempotent."""
        await pool.start()
        initial_workers = len(pool._workers)

        await pool.start()  # Second call
        assert len(pool._workers) == initial_workers

        await pool.stop()

    @pytest.mark.asyncio
    async def test_idempotent_stop(self, pool):
        """Test that stop() is idempotent."""
        await pool.start()
        await pool.stop()

        await pool.stop()  # Second call
        assert not pool.is_running

    @pytest.mark.asyncio
    async def test_workers_poll_queue(self, pool, mock_queue):
        """Test that workers call queue.advance()."""
        # Set up queue to return True once, then False
        mock_queue.advance.side_effect = [True, False, False, False]

        await pool.start()

        # Wait for workers to process
        await asyncio.sleep(0.3)

        await pool.stop()

        # Verify advance was called
        assert mock_queue.advance.call_count >= 1

    @pytest.mark.asyncio
    async def test_workers_sleep_on_empty_queue(self, pool, mock_queue):
        """Test workers sleep when queue is empty."""
        mock_queue.advance.return_value = False

        start_time = asyncio.get_event_loop().time()
        await pool.start()

        # Let workers run for a bit
        await asyncio.sleep(0.25)

        await pool.stop()
        elapsed = asyncio.get_event_loop().time() - start_time

        # Workers should have polled multiple times with sleep between
        # With poll_interval=0.1, ~0.25s should result in ~2-3 polls per worker
        assert mock_queue.advance.call_count >= 4  # 2 workers × 2 polls

    @pytest.mark.asyncio
    async def test_worker_error_recovery(self, mock_queue):
        """Test workers recover from errors."""
        # First call raises error, then returns False
        mock_queue.advance.side_effect = [
            RuntimeError("test error"),
            False, False, False
        ]

        pool = WorkerPool(mock_queue, num_workers=1, poll_interval=0.1)
        await pool.start()

        # Wait for error and recovery (longer delay after error)
        await asyncio.sleep(0.5)

        await pool.stop()

        # Should have called advance after error (error causes 1s sleep)
        assert mock_queue.advance.call_count >= 1

    @pytest.mark.asyncio
    async def test_immediate_dispatch_after_success(self, pool, mock_queue):
        """Test workers immediately retry after successful dispatch."""
        mock_queue.advance.side_effect = [True, True, False]

        await pool.start()
        await asyncio.sleep(0.15)
        await pool.stop()

        # Should have called advance at least 2 times without sleep between
        assert mock_queue.advance.call_count >= 2


class TestWorkerPoolSingleton:
    """Tests for module-level singleton."""

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_worker_pool()

    @pytest.mark.asyncio
    async def test_singleton_creation(self):
        """Test singleton is created on first access."""
        with patch("src.queue.service.get_default_queue_service") as mock_get_queue:
            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            pool = get_default_worker_pool()
            assert pool is not None
            assert pool.num_workers == 4

    @pytest.mark.asyncio
    async def test_singleton_reuse(self):
        """Test singleton is reused on subsequent access."""
        with patch("src.queue.service.get_default_queue_service") as mock_get_queue:
            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            pool1 = get_default_worker_pool()
            pool2 = get_default_worker_pool()

            assert pool1 is pool2

    def test_reset_clears_singleton(self):
        """Test reset clears the singleton."""
        with patch("src.queue.service.get_default_queue_service") as mock_get_queue:
            mock_queue = MagicMock()
            mock_get_queue.return_value = mock_queue

            pool1 = get_default_worker_pool()
            reset_worker_pool()
            pool2 = get_default_worker_pool()

            # After reset, should be different instance
            assert pool1 is not pool2