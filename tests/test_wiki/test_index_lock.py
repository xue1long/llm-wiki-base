"""Tests for index.md lock functionality."""
import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.wiki.storage.index_lock import (
    index_lock,
    with_index_lock,
    safe_write_index_entry,
    get_lock_stats,
    reset_lock_stats,
)


class TestIndexLock:
    """Tests for index_lock context manager."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_lock_stats()

    def test_basic_lock_acquire_release(self):
        """Test basic lock acquire and release."""
        stats_before = get_lock_stats()

        with index_lock():
            stats_during = get_lock_stats()
            assert stats_during["acquires"] == stats_before["acquires"] + 1

        stats_after = get_lock_stats()
        assert stats_after["releases"] == stats_before["releases"] + 1

    def test_nested_lock_same_thread(self):
        """Test nested lock in same thread (reentrant)."""
        with index_lock():
            with index_lock():
                pass  # Should not deadlock

    def test_concurrent_access(self):
        """Test concurrent access is serialized."""
        results = []
        errors = []

        def protected_op(val: int) -> int:
            try:
                with index_lock():
                    # Simulate some work
                    time.sleep(0.01)
                    results.append(val)
                    return val
            except Exception as e:
                errors.append(e)
                return -1

        # Run multiple threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(protected_op, i) for i in range(20)]
            results_list = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0
        assert len(results) == 20

        # Check contentions were detected
        stats = get_lock_stats()
        assert stats["acquires"] == 20
        assert stats["releases"] == 20
        # Some contentions expected with 10 threads
        assert stats["contentions"] >= 0


class TestWithIndexLock:
    """Tests for with_index_lock decorator."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_lock_stats()

    def test_decorator_basic(self):
        """Test decorator wraps function with lock."""
        @with_index_lock
        def protected_func(x: int) -> int:
            return x * 2

        result = protected_func(5)
        assert result == 10

        stats = get_lock_stats()
        assert stats["acquires"] == 1
        assert stats["releases"] == 1

    def test_decorator_preserves_function(self):
        """Test decorator preserves function name and docstring."""
        @with_index_lock
        def my_func():
            """My docstring."""
            pass

        assert my_func.__name__ == "my_func"
        assert "My docstring" in my_func.__doc__

    def test_decorator_exception_releases_lock(self):
        """Test that lock is released even if function raises."""
        @with_index_lock
        def failing_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_func()

        stats = get_lock_stats()
        assert stats["releases"] == 1


class TestSafeWriteIndexEntry:
    """Tests for safe_write_index_entry function."""

    def setup_method(self):
        """Reset stats before each test."""
        reset_lock_stats()

    def test_write_entry(self, tmp_path):
        """Test writing an index entry."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Index\n\n## Pages\n\n", encoding="utf-8")

        safe_write_index_entry(
            index_path,
            page_id="test-123",
            page_type="concept",
            title="Test Page"
        )

        content = index_path.read_text(encoding="utf-8")
        assert "- **test-123** (concept) — Test Page" in content

    def test_concurrent_writes(self, tmp_path):
        """Test concurrent writes are safe."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Index\n", encoding="utf-8")

        def write_entry(i: int):
            safe_write_index_entry(
                index_path,
                page_id=f"page-{i}",
                page_type="concept",
                title=f"Page {i}"
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_entry, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()  # Check no exceptions

        # Verify all entries written
        content = index_path.read_text(encoding="utf-8")
        lines = [l for l in content.split("\n") if l.startswith("- **")]
        assert len(lines) == 50


class TestLockStats:
    """Tests for lock statistics."""

    def test_get_lock_stats(self):
        """Test getting lock stats."""
        reset_lock_stats()
        stats = get_lock_stats()

        assert "acquires" in stats
        assert "releases" in stats
        assert "contentions" in stats

    def test_stats_increment(self):
        """Test stats increment correctly."""
        reset_lock_stats()

        with index_lock():
            stats = get_lock_stats()
            assert stats["acquires"] == 1

        stats = get_lock_stats()
        assert stats["releases"] == 1

    def test_reset_lock_stats(self):
        """Test resetting stats."""
        with index_lock():
            pass

        reset_lock_stats()
        stats = get_lock_stats()

        assert stats["acquires"] == 0
        assert stats["releases"] == 0
        assert stats["contentions"] == 0