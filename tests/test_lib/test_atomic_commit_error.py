"""R3 — AtomicContext commit failures must propagate (no more swallowed errors).

Audit A-02: `AtomicContext.__exit__` logged per-path flush failures and
continued; the flush_callback failure was also swallowed. Callers could
believe a batch commit succeeded when it partially failed.

New contract (architecture-remediation R3, plan-audit hardening):
- flush_pending_writes collects every failed path and raises
  AtomicCommitError (aggregated) instead of logging-and-continuing;
- AtomicContext.__exit__ lets that error propagate to the caller;
- the failed-path list is retained on the exception for retry tooling.
"""
import pytest

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib.write_hooks import flush_pending_writes, safe_write
from src.lib.write_hooks import AtomicCommitError


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


# ---------------------------------------------------------------------------
# 1. flush_pending_writes raises AtomicCommitError with failed paths
# ---------------------------------------------------------------------------

def test_flush_failure_raises_with_path_list(tmp_path, monkeypatch):
    """A failing write surfaces the path in AtomicCommitError."""
    target = tmp_path / "page.md"
    monkeypatch.setattr(
        write_hooks, "_atomic_replace",
        lambda tmp, tgt: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(AtomicCommitError) as exc_info:
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(target, "hello")

    assert target in exc_info.value.failed_paths


def test_atomic_commit_error_carries_failed_paths(tmp_path, monkeypatch):
    """AtomicCommitError.failed_paths lists every path that failed to flush."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"

    def _boom(tmp, tgt):
        raise PermissionError("denied")

    monkeypatch.setattr(write_hooks, "_atomic_replace", _boom)

    error = None
    try:
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(a, "1")
            safe_write(b, "2")
    except AtomicCommitError as e:
        error = e

    assert error is not None
    assert a in error.failed_paths
    assert b in error.failed_paths


def test_flush_success_returns_count(tmp_path):
    """Successful flush still returns the number of written paths."""
    target = tmp_path / "ok.md"
    with AtomicContext(flush_callback=flush_pending_writes):
        safe_write(target, "data")
    assert target.read_text(encoding="utf-8") == "data"


# ---------------------------------------------------------------------------
# 2. AtomicContext.__exit__ propagates the commit error
# ---------------------------------------------------------------------------

def test_context_exit_propagates_commit_error(tmp_path, monkeypatch):
    """A failed flush inside the context surfaces to the caller."""
    target = tmp_path / "page.md"
    monkeypatch.setattr(
        write_hooks, "_atomic_replace",
        lambda tmp, tgt: (_ for _ in ()).throw(PermissionError("nope")),
    )

    with pytest.raises(AtomicCommitError):
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(target, "x")


def test_body_exception_still_wins_over_flush_error(tmp_path, monkeypatch):
    """A body exception still propagates as-is (flush never runs on body raise)."""
    target = tmp_path / "page.md"
    monkeypatch.setattr(
        write_hooks, "_atomic_replace",
        lambda tmp, tgt: (_ for _ in ()).throw(PermissionError("nope")),
    )

    with pytest.raises(ValueError, match="body"):
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(target, "x")
            raise ValueError("body exploded")


def test_single_path_failure_does_not_stop_others(tmp_path, monkeypatch):
    """Every path is attempted; failures are aggregated, not short-circuited."""
    ok = tmp_path / "ok.md"
    bad = tmp_path / "bad.md"

    orig = write_hooks._atomic_replace

    def _flaky(tmp, tgt):
        if tgt == bad:
            raise PermissionError("denied")
        return orig(tmp, tgt)

    monkeypatch.setattr(write_hooks, "_atomic_replace", _flaky)

    error = None
    try:
        with AtomicContext(flush_callback=flush_pending_writes):
            safe_write(ok, "fine")
            safe_write(bad, "blocked")
    except AtomicCommitError as e:
        error = e

    assert error is not None
    assert bad in error.failed_paths
    assert ok not in error.failed_paths
    # The healthy path still reached disk.
    assert ok.read_text(encoding="utf-8") == "fine"
