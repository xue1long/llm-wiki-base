from pathlib import Path

import pytest

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib.write_hooks import AtomicCommitError


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_atomic_flush_attempts_all_paths_and_aggregates_failures(monkeypatch, tmp_path):
    """R3: a failed write does not starve the rest; failures are aggregated.

    Old behaviour: flush looped over safe_write and *isolated* each failure
    (logged-and-continued, no exception). R3 (audit A-02) keeps the
    try-every-path property but raises AtomicCommitError with the failed
    path list so the caller can mark the task FAILED.
    """
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"

    # Break the atomic replace for `first` only; `second` must still flush.
    real_replace = write_hooks._atomic_replace
    attempted = []

    def flaky_replace(tmp, target):
        attempted.append(Path(target))
        if Path(target) == first:
            raise OSError("first write failed")
        return real_replace(tmp, target)

    monkeypatch.setattr(write_hooks, "_atomic_replace", flaky_replace)
    with pytest.raises(AtomicCommitError) as exc_info:
        with AtomicContext(flush_callback=write_hooks.flush_pending_writes):
            write_hooks.safe_write(first, "one")
            write_hooks.safe_write(second, "two")

    # Every path was attempted even though one failed.
    assert attempted == [first, second]
    # The failure is surfaced, not swallowed.
    assert first in exc_info.value.failed_paths
    assert second not in exc_info.value.failed_paths
    # Bucket fully drained.
    assert write_hooks._current_bucket() == {}


def test_atomic_context_clears_pending_before_callback(tmp_path):
    target = tmp_path / "target.txt"
    observed = []

    def callback():
        observed.append(dict(write_hooks._current_bucket()))

    with AtomicContext(flush_callback=callback):
        write_hooks.safe_write(target, "content")

    assert observed == [{}]
    assert write_hooks._current_bucket() == {}
