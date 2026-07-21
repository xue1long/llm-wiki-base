import pytest
import tempfile
from pathlib import Path
from src.sync.snapshot_store import SnapshotStore


def test_snapshot_store_set_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SnapshotStore(Path(tmpdir) / "snapshot.json")
        store.set("file.md", "abc123")
        assert store.get("file.md") == "abc123"


def test_snapshot_store_get_nonexistent():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SnapshotStore(Path(tmpdir) / "snapshot.json")
        assert store.get("nonexistent") is None


def test_snapshot_store_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "snapshot.json"
        store1 = SnapshotStore(path)
        store1.set("file.md", "abc123")

        store2 = SnapshotStore(path)
        assert store2.get("file.md") == "abc123"
        assert store2.as_dict() == {"file.md": "abc123"}


def test_snapshot_store_overwrite():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SnapshotStore(Path(tmpdir) / "snapshot.json")
        store.set("file.md", "v1")
        store.set("file.md", "v2")
        assert store.get("file.md") == "v2"


def test_compute_md5():
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "test.txt"
        f.write_text("hello")
        md5 = SnapshotStore.compute_md5(f)
        assert len(md5) == 32
        assert md5 == "5d41402abc4b2a76b9719d911017c592"


def test_compute_md5_consistency():
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "test.txt"
        f.write_text("hello")
        md5_1 = SnapshotStore.compute_md5(f)
        md5_2 = SnapshotStore.compute_md5(f)
        assert md5_1 == md5_2
