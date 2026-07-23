"""Tests for atomic-write + corrupt-recovery semantics of SnapshotStore.

Verifies I-cross-5 fix: SnapshotStore._save uses tmp+replace; _load
recovers from JSONDecodeError/OSError instead of raising.
"""
import json
import os
from pathlib import Path

from src.sync.snapshot_store import SnapshotStore


def test_save_writes_via_tmp_then_replace(tmp_path):
    """SnapshotStore._save uses tmp+replace; no torn writes."""
    p = tmp_path / "snap.json"
    store = SnapshotStore(p)
    store.set("a", "md5-a")
    store.set("b", "md5-b")
    assert p.exists()
    # tmp must have been replaced, not lingering
    assert not (tmp_path / "snap.json.tmp").exists()
    assert not p.with_name(p.name + ".tmp").exists()


def test_load_recovers_from_corrupt_file(tmp_path):
    """Existing-but-corrupt snapshot → empty dict (no raise)."""
    p = tmp_path / "snap.json"
    p.write_text('{"a": "md5-a", "x', encoding="utf-8")  # truncated
    store = SnapshotStore(p)  # must not raise
    assert store.as_dict() == {}


def test_load_recovers_from_garbage(tmp_path):
    """Non-JSON content → empty dict (no raise)."""
    p = tmp_path / "snap.json"
    p.write_text("not json at all", encoding="utf-8")
    store = SnapshotStore(p)
    assert store.as_dict() == {}


def test_load_returns_empty_when_missing(tmp_path):
    """Missing file → empty dict."""
    p = tmp_path / "snap.json"
    store = SnapshotStore(p)
    assert store.as_dict() == {}


def test_load_recovers_from_empty_file(tmp_path):
    """Zero-byte file → empty dict (no raise)."""
    p = tmp_path / "snap.json"
    p.write_text("", encoding="utf-8")
    store = SnapshotStore(p)
    assert store.as_dict() == {}


def test_round_trip_persists_entries(tmp_path):
    """set() values survive a new SnapshotStore instance."""
    p = tmp_path / "snap.json"
    s1 = SnapshotStore(p)
    s1.set("file1", "md5-1")
    s1.set("file2", "md5-2")
    # Reload
    s2 = SnapshotStore(p)
    assert s2.get("file1") == "md5-1"
    assert s2.get("file2") == "md5-2"


def test_atomic_partial_failure_leaves_target_intact(tmp_path, monkeypatch):
    """If os.replace fails, target remains the prior good state."""
    p = tmp_path / "snap.json"
    s1 = SnapshotStore(p)
    s1.set("seed", "md5-seed")
    original = json.loads(p.read_text(encoding="utf-8"))

    def broken_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", broken_replace)
    try:
        s1.set("another", "md5-another")
    except OSError:
        pass

    # Restore
    monkeypatch.undo()

    # Target should still hold the original (atomic write never partial-wrote it)
    post = json.loads(p.read_text(encoding="utf-8"))
    assert post == original


def test_compute_md5_works(tmp_path):
    """Sanity check: md5 helper still functional."""
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    assert SnapshotStore.compute_md5(f) == "5d41402abc4b2a76b9719d911017c592"
