# NKB to ruflo-kb Reuse Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 Novel-Knowledge-Base 移植可复用逻辑到 ruflo-kb，建立 Schema Registry、SnapshotStore、FileSyncWatcher 和 range_search 扩展

**Architecture:** 新增 `schemas/` 和 `sync/` 两个包目录，前者负责版本迁移，后者负责文件变更追踪。向量存储扩展在已有 `vector/lance_store.py` 上添加 range_search 方法

**Tech Stack:** Python 3.11+, watchdog, lancedb, pytest

## Global Constraints

- Python 3.11+ (ruflo-kb 基线)
- pytest 测试框架
- TDD 流程：先写测试，再实现
- 提交粒度：每任务一提交

---

## Task 1: Schema Registry

**Files:**
- Create: `src/schemas/__init__.py`
- Create: `src/schemas/registry.py`
- Create: `tests/test_schemas_registry.py`

**Interfaces:**
- Consumes: `dataclasses` (内置)
- Produces: `register_migration(from_ver, to_ver, up_fn, down_fn)`, `get_migration(from_ver, to_ver)`, `migrate_data(data, target_version)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas_registry.py
import pytest
from src.schemas.registry import (
    Migration, MIGRATIONS, register_migration,
    get_migration, migrate_data, CURRENT_VERSION
)

def test_register_and_get_migration():
    up_fn = lambda d: {**d, "schema_version": "v2.0"}
    down_fn = lambda d: {k: v for k, v in d.items() if k != "schema_version"}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    mig = get_migration("v1.0", "v2.0")
    assert mig is not None
    assert mig.from_version == "v1.0"
    assert mig.to_version == "v2.0"

def test_migrate_data_up():
    up_fn = lambda d: {**d, "schema_version": "v2.0", "upgraded": True}
    down_fn = lambda d: {k: v for k, v in d.items() if k not in ("schema_version", "upgraded")}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    data = {"title": "test", "schema_version": "v1.0"}
    result = migrate_data(data, "v2.0")
    assert result["schema_version"] == "v2.0"
    assert result["upgraded"] is True
    assert result["title"] == "test"

def test_migrate_same_version_returns_original():
    data = {"schema_version": "v2.0", "title": "test"}
    result = migrate_data(data, "v2.0")
    assert result == data

def test_migrate_unknown_version_raises():
    data = {"schema_version": "v99.0"}
    with pytest.raises(ValueError, match="No migration path"):
        migrate_data(data, "v2.0")

def test_migration_up_and_down():
    up_fn = lambda d: {**d, "schema_version": "v2.0"}
    down_fn = lambda d: {k: v for k, v in d.items() if k != "schema_version"}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    mig = get_migration("v1.0", "v2.0")
    original = {"title": "test", "schema_version": "v1.0"}
    migrated = mig.up(original)
    assert migrated["schema_version"] == "v2.0"

    original_restored = mig.down(migrated)
    assert "schema_version" not in original_restored
    assert original_restored["title"] == "test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas_registry.py -v`
Expected: FAIL with "import error: cannot import name 'registry' from 'src.schemas'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/schemas/__init__.py
from .registry import (
    Migration,
    MIGRATIONS,
    register_migration,
    get_migration,
    migrate_data,
    CURRENT_VERSION,
)

__all__ = [
    "Migration",
    "MIGRATIONS",
    "register_migration",
    "get_migration",
    "migrate_data",
    "CURRENT_VERSION",
]
```

```python
# src/schemas/registry.py
"""
Schema Registry - 知识库版本映射 + 迁移路由
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

CURRENT_VERSION = "v1.0"

MIGRATIONS: dict[tuple[str, str], "Migration"] = {}

@dataclass
class Migration:
    from_version: str
    to_version: str
    up_fn: Callable[[dict], dict] = field(repr=False)
    down_fn: Callable[[dict], dict] = field(repr=False)

    def up(self, data: dict) -> dict:
        return self.up_fn(data)

    def down(self, data: dict) -> dict:
        return self.down_fn(data)

def register_migration(
    from_ver: str,
    to_ver: str,
    up_fn: Callable[[dict], dict],
    down_fn: Callable[[dict], dict],
) -> None:
    """注册一个版本迁移路径"""
    MIGRATIONS[(from_ver, to_ver)] = Migration(from_ver, to_ver, up_fn, down_fn)

def get_migration(from_version: str, to_version: str) -> Optional[Migration]:
    """获取指定版本的迁移器"""
    return MIGRATIONS.get((from_version, to_version))

def migrate_data(data: dict, target_version: str = CURRENT_VERSION) -> dict:
    """迁移数据到目标版本"""
    current_version = data.get("schema_version", "v1.0")
    if current_version == target_version:
        return data
    migration = get_migration(current_version, target_version)
    if not migration:
        raise ValueError(f"No migration path from {current_version} to {target_version}")
    return migration.up(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/schemas/ tests/test_schemas_registry.py
git commit -m "feat: add schema registry for version migration"
```

---

## Task 2: SnapshotStore

**Files:**
- Create: `src/sync/__init__.py`
- Create: `src/sync/snapshot_store.py`
- Create: `tests/test_snapshot_store.py`

**Interfaces:**
- Consumes: `pathlib.Path`, `hashlib` (内置)
- Produces: `SnapshotStore(path)`, `store.get(key)`, `store.set(key, value)`, `store.as_dict()`, `SnapshotStore.compute_md5(path)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snapshot_store.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_snapshot_store.py -v`
Expected: FAIL with "cannot import name 'snapshot_store' from 'src.sync'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/sync/__init__.py
from .snapshot_store import SnapshotStore

__all__ = ["SnapshotStore"]
```

```python
# src/sync/snapshot_store.py
"""
文件快照存储 - 追踪知识库文件 md5 变化
"""
import hashlib
import json
from pathlib import Path
from typing import Optional

class SnapshotStore:
    """JSON 快照存储：文件名 → md5"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def as_dict(self) -> dict[str, str]:
        return dict(self._data)

    @staticmethod
    def compute_md5(file_path: Path) -> str:
        return hashlib.md5(file_path.read_bytes()).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_snapshot_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync/ tests/test_snapshot_store.py
git commit -m "feat: add SnapshotStore for file change tracking"
```

---

## Task 3: FileSyncWatcher

**Files:**
- Create: `src/sync/file_watcher.py`
- Create: `tests/test_file_watcher.py`

**Interfaces:**
- Consumes: `SnapshotStore`, `watchdog.observers.Observer`
- Produces: `FileSyncWatcher(root, snapshot_store, on_change)`, `watcher.scan_once()`, `watcher.start_watch()`, `watcher.stop()`

**Constraints:**
- 需要 `pip install watchdog`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_file_watcher.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_file_watcher.py -v`
Expected: FAIL with "cannot import name 'file_watcher' from 'src.sync'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/sync/file_watcher.py
"""
文件监听 + 增量同步
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_file_watcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sync/file_watcher.py tests/test_file_watcher.py
git commit -m "feat: add FileSyncWatcher for directory monitoring"
```

---

## Task 4: LanceStore range_search

**Files:**
- Modify: `src/vector/lance_store.py`
- Create: `tests/test_vector/test_range_search.py`

**Interfaces:**
- Consumes: `lancedb`, `numpy`
- Produces: `LanceStore.range_search(query, threshold)` → `list[tuple[Document, float]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vector/test_range_search.py
import pytest
import numpy as np
from src.vector.lance_store import LanceStore, Document

@pytest.fixture
def store():
    s = LanceStore(":memory:")
    s.add(Document(id="1", text="apple fruit", embedding=[1.0, 0.0]))
    s.add(Document(id="2", text="car vehicle", embedding=[0.0, 1.0]))
    s.add(Document(id="3", text="fruit apple juice", embedding=[0.9, 0.1]))
    return s

def test_range_search_returns_matches_above_threshold(store):
    results = store.range_search("fruits", threshold=0.85)
    ids = [doc.id for doc, _ in results]
    assert "1" in ids
    assert "3" in ids
    assert "2" not in ids

def test_range_search_respects_threshold(store):
    results = store.range_search("fruits", threshold=0.95)
    assert len(results) == 0

def test_range_search_returns_similarity_scores(store):
    results = store.range_search("apple", threshold=0.5)
    for doc, sim in results:
        assert 0.5 <= sim <= 1.0

def test_range_search_empty_results(store):
    results = store.range_search("xyznonexistent", threshold=0.99)
    assert len(results) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vector/test_range_search.py -v`
Expected: FAIL with "LanceStore has no attribute 'range_search'"

- [ ] **Step 3: Write minimal implementation**

```python
# 在 LanceStore 类中添加以下方法

def range_search(self, query: str, threshold: float = 0.85) -> list[tuple[Document, float]]:
    """
    范围检索：返回相似度 >= threshold 的所有文档

    Args:
        query: 查询文本
        threshold: 相似度阈值 [0, 1]

    Returns:
        [(Document, similarity_score), ...] 按相似度降序排列
    """
    qvec = self._embedder.embed(query)
    q_norm = np.linalg.norm(qvec)
    if q_norm == 0:
        return []

    results = []
    for record in self._table.to_batches():
        for i in range(len(record["id"])):
            doc_id = record["id"][i].as_py()
            text = record["text"][i].as_py()
            embedding = np.array(record["embedding"][i].as_py())

            dot = np.dot(qvec, embedding)
            norm_product = q_norm * np.linalg.norm(embedding)
            if norm_product == 0:
                continue
            similarity = dot / norm_product

            if similarity >= threshold:
                results.append((Document(id=doc_id, text=text), float(similarity)))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
```

**在文件顶部添加 import**:

```python
import numpy as np
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vector/test_range_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vector/lance_store.py tests/test_vector/test_range_search.py
git commit -m "feat: add range_search to LanceStore for threshold-based retrieval"
```

---

## Task 5: InboxManager 集成 FileSyncWatcher

**Files:**
- Modify: `src/inbox/manager.py`
- Create: `tests/test_inbox/test_watcher_integration.py`

**Interfaces:**
- Consumes: `FileSyncWatcher`, `SnapshotStore`, `InboxManager`
- Produces: `InboxManager.watch_pending(on_change)`, `InboxManager._snapshot`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inbox/test_watcher_integration.py
import pytest
import tempfile
from pathlib import Path
from src.inbox.manager import InboxManager
from src.sync.snapshot_store import SnapshotStore
from src.sync.file_watcher import FileChange

def test_inbox_manager_snapshot_initialized():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox = InboxManager(tmpdir)
        inbox.ensure_dirs()

        assert hasattr(inbox, "_snapshot")
        assert isinstance(inbox._snapshot, SnapshotStore)

def test_inbox_manager_watch_pending_returns_watcher():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox = InboxManager(tmpdir)
        inbox.ensure_dirs()

        changes = []
        watcher = inbox.watch_pending(lambda c: changes.append(c))

        assert watcher is not None
        watcher.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inbox/test_watcher_integration.py -v`
Expected: FAIL with "InboxManager has no attribute '_snapshot' or 'watch_pending'"

- [ ] **Step 3: Write minimal implementation**

在 `src/inbox/manager.py` 中:

1. 添加 import:
```python
from src.sync.snapshot_store import SnapshotStore
from src.sync.file_watcher import FileSyncWatcher
```

2. 在 `InboxManager.__init__` 中添加:
```python
def __init__(self, base_path: str = "Inbox"):
    self.base_path = Path(base_path)
    self.pending_path = self.base_path / "Pending"
    self.processing_path = self.base_path / "Processing"
    self.error_path = self.base_path / "Error"
    self._snapshot = SnapshotStore(self.base_path / ".file_snapshot.json")
```

3. 添加新方法:
```python
def watch_pending(self, on_change: callable) -> FileSyncWatcher:
    """启动对 Pending 目录的文件监听"""
    watcher = FileSyncWatcher(self.pending_path, self._snapshot, on_change)
    watcher.start_watch()
    return watcher
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_inbox/test_watcher_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/inbox/manager.py tests/test_inbox/test_watcher_integration.py
git commit -m "feat: integrate FileSyncWatcher into InboxManager"
```

---

## Self-Review Checklist

1. **Spec coverage**: 所有 5 个任务覆盖了 Schema Registry、SnapshotStore、FileSyncWatcher、range_search、Inbox 集成
2. **Placeholder scan**: 无 TBD/TODO，每步都有完整代码
3. **Type consistency**: `FileChange`, `ChangeType`, `SnapshotStore` 等类型在所有任务中一致

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-21-nkb-to-ruflo-migration.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
