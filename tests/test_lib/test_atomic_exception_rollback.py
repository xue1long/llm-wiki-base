"""AtomicContext exception rollback — write succeeds then exception -> no writes.

When the body of an `AtomicContext` raises, the pending buffered writes
MUST NOT be committed to disk. Previously, `AtomicContext.__exit__`
flushed pending writes regardless of `exc_val`, which meant a failed
operation would commit already-buffered writes before propagating the
exception — a classic partial-state corruption footgun.

Contract:
    - exc_type is None  -> flush pending writes (normal commit point).
    - exc_type is not None -> DISCARD pending writes; propagate exception.

This file pins both halves so neither side regresses.
"""
from pathlib import Path

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib.write_hooks import safe_write, DELETE_SENTINEL


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_exception_in_body_discards_pending_writes(tmp_path):
    """A raised exception must not commit buffered writes to disk."""
    target = tmp_path / "page.md"
    # Pre-existing file — AtomicContext rollback must NOT overwrite it.
    target.write_text("OLD", encoding="utf-8")

    raised = None
    try:
        with AtomicContext(flush_callback=lambda: None):
            safe_write(target, "NEW (should not land)")
            raise RuntimeError("body exploded")
    except RuntimeError as exc:
        raised = exc

    # Original exception still propagates.
    assert raised is not None
    assert str(raised) == "body exploded"
    # File content unchanged — buffered write was discarded.
    assert target.read_text(encoding="utf-8") == "OLD"
    # Pending bucket cleared (no leakage to a future context).
    assert write_hooks._current_bucket() == {}


def test_exception_in_body_discards_delete_sentinels(tmp_path):
    """DELETE_SENTINEL buffered while suspended must NOT unlink when body raises."""
    victim = tmp_path / "victim.md"
    victim.write_text("keep me", encoding="utf-8")

    try:
        with AtomicContext():
            safe_write(victim, DELETE_SENTINEL)
            raise ValueError("body exploded")
    except ValueError:
        pass

    # File still exists — the deletion was discarded.
    assert victim.read_text(encoding="utf-8") == "keep me"


def test_no_exception_still_commits_pending_writes(tmp_path):
    """Normal path (no exception) must still commit — no regression.

    When a flush_callback is supplied, the AtomicContext is the commit
    point and buffered writes must reach disk.
    """
    target = tmp_path / "page.md"
    target.write_text("OLD", encoding="utf-8")
    with AtomicContext(flush_callback=lambda: write_hooks.flush_pending_writes()):
        safe_write(target, "FRESH")
    assert target.read_text(encoding="utf-8") == "FRESH"


def test_exception_only_discards_pending_after_outer_exit(tmp_path):
    """Nested AtomicContext: exception in inner body should also discard."""
    target = tmp_path / "page.md"

    try:
        with AtomicContext():
            safe_write(target, "would-be-written")
            with AtomicContext():
                pass  # inner exits cleanly
            raise RuntimeError("after inner exit")
    except RuntimeError:
        pass

    assert not target.exists()


def test_callback_not_called_when_body_raises(tmp_path):
    """The flush_callback must NOT fire when the body raises."""
    calls = []
    try:
        with AtomicContext(flush_callback=lambda: calls.append("fired")):
            safe_write(tmp_path / "x.md", "x")
            raise RuntimeError("no flush")
    except RuntimeError:
        pass
    assert calls == []