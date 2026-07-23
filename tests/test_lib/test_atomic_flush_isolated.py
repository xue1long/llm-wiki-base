from pathlib import Path

from src.lib import write_hooks
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_atomic_flush_isolates_write_failures(monkeypatch, tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    real_safe_write = write_hooks.safe_write
    writes = []

    def flush_one_write(path, content):
        if write_hooks.is_suspended():
            return real_safe_write(path, content)
        writes.append((Path(path), content))
        if Path(path) == first:
            raise OSError("first write failed")

    monkeypatch.setattr(write_hooks, "safe_write", flush_one_write)
    with AtomicContext(flush_callback=lambda: write_hooks.flush_pending_writes()):
        write_hooks.safe_write(first, "one")
        write_hooks.safe_write(second, "two")

    assert writes == [(first, "one"), (second, "two")]
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
