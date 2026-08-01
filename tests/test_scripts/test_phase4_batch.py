"""Unit tests for scripts/phase4_batch.py pure helpers.

R0-2 (empty/all-failed batch guard) and R1-1 phase4 side (state
double-tool tolerance + status-independent ``completed_files`` read).
phase4_batch's top-level imports are stdlib-only
(argparse/asyncio/json/logging/sys/time/pathlib); ``src`` imports are
deferred to call time, so importing it here pulls no heavy deps.
"""
from scripts.phase4_batch import _decide_abort


# ---------------------------------------------------------------------------
# R0-2 · _decide_abort — empty/all-failed batch guard (B4)
# ---------------------------------------------------------------------------

def test_decide_abort_all_failed():
    """① ok==0, err>0 → abort (all files failed)."""
    abort, reason = _decide_abort(
        ok=0, err=3, pending=0, resume=False, completed=set(), skip=0)
    assert abort is True
    assert reason


def test_decide_abort_all_missing():
    """② ok==0, err==0, pending>0 → abort (all files missing / empty batch)."""
    abort, reason = _decide_abort(
        ok=0, err=0, pending=5, resume=False, completed=set(), skip=0)
    assert abort is True
    assert reason


def test_decide_abort_already_completed_resume():
    """③ ok==0, pending==0, resume + files⊆completed → no abort ("已完成")."""
    completed = {"raw/a.md", "raw/b.md"}
    abort, reason = _decide_abort(
        ok=0, err=0, pending=0, resume=True, completed=completed, skip=2)
    assert abort is False
    assert reason


def test_decide_abort_mixed_ok():
    """④ anything with ok>0 → no abort."""
    abort, _reason = _decide_abort(
        ok=2, err=1, pending=0, resume=False, completed=set(), skip=0)
    assert abort is False
