import pytest
import tempfile
import time
from pathlib import Path
from src.sync.snapshot_store import SnapshotStore
from src.sync.file_watcher import FileSyncWatcher, ChangeType, FileChange

def test_scan_once_detects_new_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = SnapshotStore(root / "snapshot.json")
        watcher = FileSyncWatcher(root, store)

        (root / "new.md").write_text("# Test")
        changes = watcher.scan_once()

        assert len(changes) == 1
        assert changes[0].type == ChangeType.ADDED
        assert changes[0].path.name == "new.md"

def test_scan_once_detects_modification():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        f = root / "test.md"
        f.write_text("v1")

        store = SnapshotStore(root / "snapshot.json")
        watcher = FileSyncWatcher(root, store)
        watcher.scan_once()

        time.sleep(0.1)
        f.write_text("v2")
        changes = watcher.scan_once()

        mod_changes = [c for c in changes if c.type == ChangeType.MODIFIED]
        assert len(mod_changes) == 1
        assert mod_changes[0].old_hash != mod_changes[0].new_hash

def test_scan_once_no_changes():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        f = root / "test.md"
        f.write_text("content")

        store = SnapshotStore(root / "snapshot.json")
        watcher = FileSyncWatcher(root, store)
        watcher.scan_once()

        changes = watcher.scan_once()
        assert len(changes) == 0

def test_scan_once_on_change_callback():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = SnapshotStore(root / "snapshot.json")
        callback_calls = []

        def on_change(change: FileChange):
            callback_calls.append(change)

        watcher = FileSyncWatcher(root, store, on_change)
        (root / "new.md").write_text("# Test")
        watcher.scan_once()

        assert len(callback_calls) == 1
        assert callback_calls[0].type == ChangeType.ADDED
