"""Test OptimisticLock concurrency control (Task 4.7)."""
import pytest

from src.knowledge.core.concurrency import (
    OptimisticLock,
    ConcurrencyError,
)


class TestGetVersion:
    """get_version behavior."""

    def test_new_object_returns_zero(self, tmp_path):
        """Unknown object -> version 0."""
        lock = OptimisticLock(tmp_path)
        assert lock.get_version("unknown_obj") == 0

    def test_version_persists_across_instances(self, tmp_path):
        """Write version, create new OptimisticLock instance -> version preserved."""
        lock1 = OptimisticLock(tmp_path)
        lock1.release("obj_x", 7)
        lock2 = OptimisticLock(tmp_path)
        assert lock2.get_version("obj_x") == 7


class TestAcquire:
    """acquire behavior."""

    def test_succeeds_when_versions_match(self, tmp_path):
        """expected=0, current=0 -> acquire returns True."""
        lock = OptimisticLock(tmp_path)
        assert lock.acquire("obj", 0) is True

    def test_fails_when_versions_mismatch(self, tmp_path):
        """expected=0, current=2 -> acquire returns False."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 2)
        assert lock.acquire("obj", 0) is False

    def test_increments_version_on_success(self, tmp_path):
        """After acquire succeeds, version is incremented."""
        lock = OptimisticLock(tmp_path)
        assert lock.get_version("obj") == 0
        lock.acquire("obj", 0)
        assert lock.get_version("obj") == 1

    def test_does_not_change_version_on_failure(self, tmp_path):
        """After acquire fails, version remains unchanged."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 5)
        lock.acquire("obj", 0)  # mismatch -> False
        assert lock.get_version("obj") == 5


class TestRelease:
    """release behavior."""

    def test_release_updates_version(self, tmp_path):
        """release("obj", 5) -> get_version returns 5."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 5)
        assert lock.get_version("obj") == 5

    def test_release_overwrites_previous_version(self, tmp_path):
        """Multiple releases overwrite."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 3)
        lock.release("obj", 9)
        assert lock.get_version("obj") == 9


class TestWithLock:
    """with_lock behavior."""

    def test_succeeds_first_try(self, tmp_path):
        """Simple write_fn -> returns result."""
        lock = OptimisticLock(tmp_path)

        def write_fn(expected_version=0):
            return f"written_at_{expected_version}"

        result = lock.with_lock("obj", write_fn)
        assert result == "written_at_0"
        assert lock.get_version("obj") == 1

    def test_retries_on_conflict(self, tmp_path):
        """write_fn fails once then succeeds -> retries and returns."""
        lock = OptimisticLock(tmp_path)
        attempts = []

        def write_fn(expected_version=0):
            attempts.append(expected_version)
            if len(attempts) < 2:
                raise ConcurrencyError("obj", 1)
            return "success_on_retry"

        result = lock.with_lock("obj", write_fn)
        assert result == "success_on_retry"
        assert len(attempts) == 2

    def test_exhausts_retries(self, tmp_path):
        """write_fn always fails -> raises ConcurrencyError after 3 attempts."""
        lock = OptimisticLock(tmp_path)
        attempts = []

        def write_fn(expected_version=0):
            attempts.append(expected_version)
            raise ConcurrencyError("obj", len(attempts))

        with pytest.raises(ConcurrencyError) as exc_info:
            lock.with_lock("obj", write_fn)

        assert exc_info.value.object_id == "obj"
        assert exc_info.value.attempts == 3
        assert len(attempts) == 3

    def test_passes_extra_args_to_write_fn(self, tmp_path):
        """Extra *args and **kwargs are forwarded to write_fn."""
        lock = OptimisticLock(tmp_path)
        captured = {}

        def write_fn(x, expected_version=0, note=""):
            captured["x"] = x
            captured["expected_version"] = expected_version
            captured["note"] = note
            return "ok"

        result = lock.with_lock("obj", write_fn, 42, note="hello")
        assert result == "ok"
        assert captured["x"] == 42
        assert captured["expected_version"] == 0
        assert captured["note"] == "hello"


class TestConcurrencyError:
    """ConcurrencyError details."""

    def test_contains_object_id_and_attempts(self):
        """ConcurrencyError stores object_id and attempts."""
        err = ConcurrencyError("my-obj-123", 3)
        assert err.object_id == "my-obj-123"
        assert err.attempts == 3

    def test_string_representation(self):
        """ConcurrencyError has a meaningful message."""
        err = ConcurrencyError("abc", 3)
        assert "abc" in str(err)
        assert "3" in str(err)


class TestMaxRetries:
    """MAX_RETRIES constant."""

    def test_max_retries_is_three(self):
        """MAX_RETRIES = 3."""
        assert OptimisticLock.MAX_RETRIES == 3


class TestIndependentVersions:
    """Concurrent versions are independent."""

    def test_independent_versions(self, tmp_path):
        """obj_a and obj_b have separate versions."""
        lock = OptimisticLock(tmp_path)

        lock.release("obj_a", 5)
        lock.release("obj_b", 12)

        assert lock.get_version("obj_a") == 5
        assert lock.get_version("obj_b") == 12

    def test_independent_acquisition(self, tmp_path):
        """Acquiring lock for obj_a does not affect obj_b."""
        lock = OptimisticLock(tmp_path)

        lock.release("obj_a", 3)
        lock.release("obj_b", 3)

        # Acquire for obj_a only
        assert lock.acquire("obj_a", 3) is True

        # obj_a version bumped
        assert lock.get_version("obj_a") == 4
        # obj_b version unchanged
        assert lock.get_version("obj_b") == 3


class TestGetLockInfo:
    """get_lock_info metadata."""

    def test_returns_version(self, tmp_path):
        """get_lock_info returns dict with version."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 7)
        info = lock.get_lock_info("obj")
        assert info["version"] == 7

    def test_returns_zero_for_new_object(self, tmp_path):
        """get_lock_info for unknown object returns version 0."""
        lock = OptimisticLock(tmp_path)
        info = lock.get_lock_info("never_written")
        assert info["version"] == 0

    def test_includes_last_modified_when_file_exists(self, tmp_path):
        """get_lock_info includes last_modified for existing version file."""
        lock = OptimisticLock(tmp_path)
        lock.release("obj", 1)
        info = lock.get_lock_info("obj")
        assert "last_modified" in info
        assert isinstance(info["last_modified"], float)
