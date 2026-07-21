"""
文件监听 + 增量同步
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from src.sync.snapshot_store import SnapshotStore

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    raise RuntimeError("watchdog not installed; pip install watchdog")

class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"

@dataclass
class FileChange:
    path: Path
    type: ChangeType
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None

class FileSyncWatcher:
    """文件监听 + 增量同步"""

    def __init__(
        self,
        root: Path,
        snapshot_store: SnapshotStore,
        on_change: Optional[Callable[[FileChange], None]] = None,
    ):
        self.root = Path(root)
        self.snapshot = snapshot_store
        self.on_change = on_change
        self._observer: Optional[Observer] = None

    def scan_once(self) -> list[FileChange]:
        """扫描一次，返回变更列表，并更新快照"""
        changes: list[FileChange] = []

        for file_path in self.root.rglob("*.md"):
            current_hash = SnapshotStore.compute_md5(file_path)
            prev_hash = self.snapshot.get(file_path.name)

            if prev_hash is None:
                changes.append(FileChange(file_path, ChangeType.ADDED, new_hash=current_hash))
            elif prev_hash != current_hash:
                changes.append(FileChange(
                    file_path, ChangeType.MODIFIED,
                    old_hash=prev_hash, new_hash=current_hash
                ))
            self.snapshot.set(file_path.name, current_hash)

        if self.on_change:
            for c in changes:
                self.on_change(c)
        return changes

    def start_watch(self) -> None:
        """启动后台监听"""
        class Handler(FileSystemEventHandler):
            def __init__(self, callback: Callable[[str], None]):
                self.callback = callback

            def on_modified(self, event):
                if event.src_path.endswith(".md"):
                    self.callback(event.src_path)

        self._observer = Observer()
        self._observer.schedule(
            Handler(lambda p: self.scan_once()),
            str(self.root),
            recursive=True,
        )
        self._observer.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
