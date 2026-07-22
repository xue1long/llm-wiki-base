import threading

import pytest

from src.cli_ext.atomic_cmd import cmd_atomic_status, cmd_budget_estimate, cmd_budget_check
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib import write_hooks


def setup_function(_):
    __reset_for_testing()
    write_hooks._pending_writes.clear()


def test_cmd_atomic_status_idle(capsys):
    args = type("Args", (), {})()
    cmd_atomic_status(args)
    out = capsys.readouterr().out
    assert "idle" in out


def test_cmd_atomic_status_suspended(capsys):
    with AtomicContext():
        args = type("Args", (), {})()
        cmd_atomic_status(args)
        out = capsys.readouterr().out
        assert "suspended" in out or "active" in out


def test_cmd_budget_estimate(capsys, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello world" * 100)  # 1100 chars
    args = type("Args", (), {"path": str(f)})()
    cmd_budget_estimate(args)
    out = capsys.readouterr().out
    assert "550" in out  # 1100 / 2


def test_cmd_budget_check_fits(capsys, tmp_path):
    f = tmp_path / "small.md"
    f.write_text("small content")  # 13 chars
    args = type("Args", (), {"path": str(f), "model": "gpt-4o-mini"})()
    cmd_budget_check(args)
    out = capsys.readouterr().out
    assert "fits" in out.lower() or "ok" in out.lower()


def test_cmd_budget_check_exceeds(capsys, tmp_path):
    f = tmp_path / "huge.md"
    f.write_text("x" * 1000000)  # 500K tokens, way over gpt-4o-mini... actually fits
    # Use a tiny model to force exceed
    args = type("Args", (), {"path": str(f), "model": "qwen2.5:7b"})()  # 32K context
    with pytest.raises(SystemExit) as exc_info:
        cmd_budget_check(args)
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "exceeds" in out or "over" in out or "fail" in out.lower() or "✗" in out
