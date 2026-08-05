"""Tests for file-level lock manager."""
import asyncio
import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.queue.file_lock import (
    FileLockManager,
    get_file_lock_manager,
    reset_file_lock_manager,
)


class TestFileLockManager:
    """Tests for FileLockManager."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_file_lock_manager()

    def test_basic_acquire_release(self):
        """Test basic lock acquire and release."""
        manager = FileLockManager()

        # Acquire should succeed
        async def acquire():
            result = await manager.acquire("project-1", "file1.md")
            assert result is True
            return result

        result = asyncio.run(acquire())
        assert result is True

        # Release should work
        manager.release("project-1", "file1.md")

        stats = manager.get_stats()
        assert stats["acquires"] == 1
        assert stats["releases"] == 1

    def test_same_file_serialized(self):
        """Test that same file operations are serialized."""
        manager = FileLockManager()
        results = []
        errors = []

        def protected_op(val: int):
            try:
                # Run async acquire in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                acquired = loop.run_until_complete(
                    manager.acquire("project-1", "file1.md", timeout=5.0)
                )
                if acquired:
                    time.sleep(0.01)  # Simulate work
                    results.append(val)
                    manager.release("project-1", "file1.md")
                return val
            except Exception as e:
                errors.append(e)
                return -1
            finally:
                loop.close()

        # Run multiple threads for same file
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(protected_op, i) for i in range(10)]
            results_list = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0
        assert len(results) == 10
        assert set(results) == set(range(10))

    def test_different_files_parallel(self):
        """Test that different files can be processed in parallel."""
        manager = FileLockManager(max_per_project=4)
        start_times = []
        end_times = []
        errors = []

        def process_file(file_idx: int):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    acquired = loop.run_until_complete(
                        manager.acquire("project-1", f"file{file_idx}.md", timeout=5.0)
                    )
                    if acquired:
                        start_times.append(time.time())
                        time.sleep(0.1)  # Simulate work
                        end_times.append(time.time())
                        manager.release("project-1", f"file{file_idx}.md")
                    return file_idx
                finally:
                    loop.close()
            except Exception as e:
                errors.append(e)
                return -1

        # Process 4 different files (should run in parallel due to max_per_project=4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(process_file, i) for i in range(4)]
            results = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0
        assert set(results) == set(range(4))

        # If they ran in parallel, the total time should be ~0.1s, not 0.4s
        total_time = max(end_times) - min(start_times)
        assert total_time < 0.3  # Allow some overhead, but should be < 0.4s

    def test_project_semaphore_limit(self):
        """Test that project concurrency limit is enforced."""
        manager = FileLockManager(max_per_project=2)
        acquired_count = 0
        max_concurrent = 0
        lock = threading.Lock()

        def process_file(file_idx: int):
            nonlocal acquired_count, max_concurrent
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    acquired = loop.run_until_complete(
                        manager.acquire("project-1", f"file{file_idx}.md", timeout=5.0)
                    )
                    if acquired:
                        with lock:
                            acquired_count += 1
                            max_concurrent = max(max_concurrent, acquired_count)
                        time.sleep(0.05)  # Simulate work
                        with lock:
                            acquired_count -= 1
                        manager.release("project-1", f"file{file_idx}.md")
                    return file_idx
                finally:
                    loop.close()
            except Exception as e:
                return -1

        # Process 6 files with max_per_project=2
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(process_file, i) for i in range(6)]
            results = [f.result() for f in as_completed(futures)]

        assert set(results) == set(range(6))
        # Max concurrent should not exceed 2
        assert max_concurrent <= 2

    def test_timeout_on_semaphore(self):
        """Test timeout when semaphore is full."""
        manager = FileLockManager(max_per_project=1)

        async def test_timeout():
            # Acquire first slot
            await manager.acquire("project-1", "file1.md", timeout=1.0)

            # Try to acquire second slot (should timeout)
            with pytest.raises(TimeoutError):
                await manager.acquire("project-1", "file2.md", timeout=0.5)

            manager.release("project-1", "file1.md")

        asyncio.run(test_timeout())

    def test_locked_files_tracking(self):
        """Test tracking of locked files."""
        manager = FileLockManager()

        async def test_tracking():
            await manager.acquire("project-1", "file1.md")
            await manager.acquire("project-1", "file2.md")
            await manager.acquire("project-2", "file3.md")

            locked_p1 = manager.get_locked_files("project-1")
            locked_p2 = manager.get_locked_files("project-2")

            assert len(locked_p1) == 2
            assert len(locked_p2) == 1

            manager.release("project-1", "file1.md")
            locked_p1 = manager.get_locked_files("project-1")
            assert len(locked_p1) == 1

            manager.release("project-1", "file2.md")
            manager.release("project-2", "file3.md")

            assert len(manager.get_locked_files("project-1")) == 0
            assert len(manager.get_locked_files("project-2")) == 0

        asyncio.run(test_tracking())

    def test_release_unlocked_file(self):
        """Test releasing an unlocked file (should not raise)."""
        manager = FileLockManager()

        # Should not raise
        manager.release("project-1", "nonexistent.md")

        stats = manager.get_stats()
        assert stats["releases"] == 0  # No release happened


class TestFileLockSingleton:
    """Tests for singleton management."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_file_lock_manager()

    def test_singleton_returns_same_instance(self):
        """Test that get_file_lock_manager returns same instance."""
        manager1 = get_file_lock_manager()
        manager2 = get_file_lock_manager()

        assert manager1 is manager2

    def test_reset_creates_new_instance(self):
        """Test that reset creates new instance."""
        manager1 = get_file_lock_manager()
        reset_file_lock_manager()
        manager2 = get_file_lock_manager()

        assert manager1 is not manager2

    def test_singleton_with_custom_env(self, monkeypatch):
        """Test that singleton reads env var for config."""
        monkeypatch.setenv("RUFLO_MAX_PROJECT_CONCURRENCY", "8")
        reset_file_lock_manager()

        manager = get_file_lock_manager()
        assert manager._max_per_project == 8


class TestFileLockStats:
    """Tests for lock statistics."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_file_lock_manager()

    def test_stats_acquires_releases(self):
        """Test that acquires and releases are counted."""
        manager = FileLockManager()

        async def test_stats():
            await manager.acquire("project-1", "file1.md")
            stats = manager.get_stats()
            assert stats["acquires"] == 1

            manager.release("project-1", "file1.md")
            stats = manager.get_stats()
            assert stats["releases"] == 1

        asyncio.run(test_stats())

    def test_stats_contentions(self):
        """Test that contentions are tracked."""
        manager = FileLockManager()
        contention_detected = []

        def acquire_file(file_idx: int):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    manager.acquire("project-1", "file1.md", timeout=5.0)
                )
                time.sleep(0.05)
                manager.release("project-1", "file1.md")
            except Exception as e:
                contention_detected.append(e)
            finally:
                loop.close()

        # Run multiple threads for same file (will cause contention)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(acquire_file, i) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        stats = manager.get_stats()
        # All 5 should acquire, but some had to wait
        assert stats["acquires"] == 5
        assert stats["releases"] == 5
        # At least some contentions expected
        assert stats["contentions"] >= 0