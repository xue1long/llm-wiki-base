from pathlib import Path

from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib.write_hooks import safe_write, flush_pending_writes, get_pending_count


def setup_function(_):
    __reset_for_testing()
    from src.lib import write_hooks
    write_hooks._reset_for_testing()


def test_safe_write_writes_directly_when_not_suspended(tmp_path):
    f = tmp_path / "a.md"
    safe_write(f, "hello")
    assert f.read_text() == "hello"
    assert get_pending_count() == 0


def test_safe_write_accumulates_when_suspended(tmp_path):
    f = tmp_path / "a.md"
    with AtomicContext():
        safe_write(f, "hello")
        assert not f.exists()  # not written yet
        assert get_pending_count() == 1
    # After exit (no flush_callback), still not written
    assert not f.exists()


def test_safe_write_accumulates_multiple_files(tmp_path):
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    with AtomicContext():
        safe_write(f1, "1")
        safe_write(f2, "2")
    assert not f1.exists() and not f2.exists()
    assert get_pending_count() == 2


def test_flush_pending_writes_writes_all(tmp_path):
    f1 = tmp_path / "a.md"
    f2 = tmp_path / "b.md"
    with AtomicContext():
        safe_write(f1, "1")
        safe_write(f2, "2")
    count = flush_pending_writes()
    assert count == 2
    assert f1.read_text() == "1"
    assert f2.read_text() == "2"


def test_safe_write_creates_parent_dirs(tmp_path):
    f = tmp_path / "deep" / "nested" / "a.md"
    safe_write(f, "hello")
    assert f.read_text() == "hello"
