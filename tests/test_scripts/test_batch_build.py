"""Tests for scripts/batch_build.py state handling (R1-1).

load_state fills missing section defaults so a state file written by another
tool (e.g. phase4's ``batch_N`` keys) never trips callers on KeyError;
save_state writes atomically (tmp + os.replace, mirroring
phase4_batch._save_state).
"""
import json
import os

import pytest

import scripts.batch_build as batch_build
from src.utils.hashing import sha256_file


# ---------------------------------------------------------------------------
# R1-1 · load_state — default sections
# ---------------------------------------------------------------------------

def test_load_state_adds_section_defaults_when_file_has_only_foreign_keys(tmp_path):
    """A state file written by another tool (only ``batch_N`` keys) must still
    expose the ``ingested`` / ``archived`` / ``failed`` sections without
    dropping the foreign keys."""
    sp = tmp_path / "batch_build_state.json"
    sp.write_text(json.dumps({"batch_1": "in-progress", "batch_2": {"ok": 5}}), encoding="utf-8")

    state = batch_build.load_state(sp)

    assert state["ingested"] == {}
    assert state["archived"] == {}
    assert state["failed"] == {}
    # existing keys preserved
    assert state["batch_1"] == "in-progress"
    assert state["batch_2"] == {"ok": 5}


def test_load_state_preserves_existing_section_contents(tmp_path):
    """Existing section contents must be kept — setdefault must not clobber."""
    sp = tmp_path / "batch_build_state.json"
    existing = {
        "ingested": {"wiki/sources/a.md": "digest-a"},
        "archived": {},
        "failed": {"wiki/sources/b.md": "boom"},
    }
    sp.write_text(json.dumps(existing), encoding="utf-8")

    state = batch_build.load_state(sp)
    assert state["ingested"] == {"wiki/sources/a.md": "digest-a"}
    assert state["archived"] == {}
    assert state["failed"] == {"wiki/sources/b.md": "boom"}


def test_load_state_returns_defaults_when_file_missing(tmp_path):
    assert batch_build.load_state(tmp_path / "does-not-exist.json") == {
        "ingested": {},
        "archived": {},
        "failed": {},
    }


def test_load_state_resets_on_corrupt_json(tmp_path):
    sp = tmp_path / "batch_build_state.json"
    sp.write_text("{ not valid json", encoding="utf-8")
    assert batch_build.load_state(sp) == {"ingested": {}, "archived": {}, "failed": {}}


# ---------------------------------------------------------------------------
# R1-1 · save_state — atomic write
# ---------------------------------------------------------------------------

def test_save_state_writes_atomically_and_replaces(tmp_path):
    sp = tmp_path / ".index" / "batch_build_state.json"
    sp.parent.mkdir(parents=True)

    batch_build.save_state(sp, {"ingested": {"a": "d1"}, "archived": {}, "failed": {}})
    batch_build.save_state(sp, {"ingested": {"a": "d2"}, "archived": {}, "failed": {}})

    assert json.loads(sp.read_text(encoding="utf-8")) == {
        "ingested": {"a": "d2"}, "archived": {}, "failed": {},
    }


def test_save_state_preserves_old_file_when_replace_fails(tmp_path, monkeypatch):
    """If os.replace raises (e.g. antivirus lock), the pre-existing state file
    must be left untouched — the write went to the .tmp sibling only."""
    sp = tmp_path / ".index" / "batch_build_state.json"
    sp.parent.mkdir(parents=True)
    old = {"ingested": {"a": "old-digest"}, "archived": {}, "failed": {}}
    sp.write_text(json.dumps(old), encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("simulated os.replace failure")

    monkeypatch.setattr(os, "replace", _boom)

    with pytest.raises(OSError):
        batch_build.save_state(sp, {"ingested": {"a": "new-digest"}, "archived": {}, "failed": {}})

    # target file still holds the old complete content
    assert json.loads(sp.read_text(encoding="utf-8")) == old


def test_batch_build_uses_shared_sha256_file():
    assert batch_build.sha256_file is sha256_file
