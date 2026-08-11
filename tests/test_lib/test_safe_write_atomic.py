"""Tests for atomic-write semantics of safe_write when not inside AtomicContext.

Verifies that the non-suspended path uses *.tmp + os.replace (so a crash mid-write
never produces a torn target file), while the suspended path keeps buffered semantics.
"""
import os

from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib import write_hooks
from src.lib.write_hooks import safe_write, get_pending_count


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_safe_write_outside_ctx_uses_tmp_then_replace(tmp_path):
    """Non-suspended path: writes to .tmp then renames over target."""
    target = tmp_path / "page.md"
    safe_write(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    # tmp must have been replaced (not lingering)
    assert not (tmp_path / "page.md.tmp").exists()
    assert not target.with_name(target.name + ".tmp").exists()
    assert get_pending_count() == 0


def test_safe_write_outside_ctx_creates_parent_dirs(tmp_path):
    """Non-suspended path also creates parent directories (via tmp)."""
    target = tmp_path / "deep" / "nested" / "page.md"
    safe_write(target, "x")
    assert target.read_text(encoding="utf-8") == "x"
    assert not target.with_name(target.name + ".tmp").exists()


def test_safe_write_outside_ctx_partial_failure_leaves_target_intact(tmp_path, monkeypatch):
    """If os.replace fails mid-write, target must be unchanged (or absent)."""
    target = tmp_path / "page.md"
    target.write_text("ORIGINAL", encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", broken_replace)
    try:
        safe_write(target, "NEW")
    except OSError:
        pass

    # Target must still hold ORIGINAL (atomic write never partial-wrote it).
    assert target.read_text(encoding="utf-8") == "ORIGINAL"


def test_safe_write_suspended_path_still_buffers(tmp_path):
    """Suspended path unchanged: write to _pending_writes, NOT to disk."""
    target = tmp_path / "page.md"
    with AtomicContext():
        safe_write(target, "buffered")
        # Nothing on disk yet
        assert not target.exists()
        # And the .tmp file is NOT created (buffered path doesn't touch disk)
        assert not (tmp_path / "page.md.tmp").exists()
        assert get_pending_count() == 1
    # After exit (no flush_callback) — still buffered, never written
    assert not target.exists()


def test_safe_write_atomic_no_torn_file_on_concurrent_rename(tmp_path, monkeypatch):
    """Rename within same filesystem = atomic on POSIX/Windows.

    We can't truly simulate a torn file, but we can verify that the target
    file content is the new content (not the old + new concatenated) after
    a successful write — i.e. os.replace semantics (full replacement).
    """
    target = tmp_path / "page.md"
    target.write_text("ORIGINAL" * 1000, encoding="utf-8")
    safe_write(target, "NEW")
    # Full replacement — no prefix/suffix from original
    content = target.read_text(encoding="utf-8")
    assert content == "NEW"
    assert "ORIGINAL" not in content


def test_safe_write_atomic_pending_writes_unaffected(tmp_path):
    """After a non-suspended write, _pending_writes must remain empty."""
    target = tmp_path / "page.md"
    safe_write(target, "hello")
    assert write_hooks._current_bucket() == {}


def test_safe_write_atomic_overwrites_existing_file(tmp_path):
    """Atomic write over existing file replaces contents cleanly."""
    target = tmp_path / "page.md"
    target.write_text("OLD", encoding="utf-8")
    safe_write(target, "NEW")
    assert target.read_text(encoding="utf-8") == "NEW"
