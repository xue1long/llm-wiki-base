"""Unit tests for scripts/phase4_batch.py pure helpers.

R0-2 (empty/all-failed batch guard) and R1-1 phase4 side (state
double-tool tolerance + status-independent ``completed_files`` read).
phase4_batch's top-level imports are stdlib-only
(argparse/asyncio/json/logging/sys/time/pathlib); ``src`` imports are
deferred to call time, so importing it here pulls no heavy deps.
"""
import json

import pytest

from scripts.phase4_batch import _batch_completed_files, _decide_abort, _load_state


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


# ---------------------------------------------------------------------------
# R1-1 · _load_state — corrupt/unreadable state file → {} (B7/D4)
# ---------------------------------------------------------------------------

def test_load_state_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", tmp_path / "nope.json")
    assert _load_state() == {}


def test_load_state_corrupt_json(tmp_path, monkeypatch):
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _load_state() == {}


def test_load_state_directory_raises_oserror(tmp_path, monkeypatch):
    """A directory at BATCH_STATE raises OSError on read_text → {} (not crash)."""
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", tmp_path)
    assert _load_state() == {}


# ---------------------------------------------------------------------------
# R1-1 · _batch_completed_files — status-independent read (F7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["committing", "partial", "committed", "postcheck_failed"])
def test_batch_completed_files_status_agnostic(tmp_path, monkeypatch, status):
    """Any entry carrying completed_files resumes from it, regardless of status."""
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text(json.dumps({
        "batch_0": {"status": status, "completed_files": ["raw/a.md", "raw/b.md"]},
    }), encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _batch_completed_files("batch_0") == {"raw/a.md", "raw/b.md"}


def test_batch_completed_files_non_dict_entry(tmp_path, monkeypatch):
    """Non-dict entry (e.g. a bare string) → empty set, not a crash."""
    state_file = tmp_path / "batch_build_state.json"
    state_file.write_text(json.dumps({"batch_0": "garbage"}), encoding="utf-8")
    monkeypatch.setattr("scripts.phase4_batch.BATCH_STATE", state_file)
    assert _batch_completed_files("batch_0") == set()
