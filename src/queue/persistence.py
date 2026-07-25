"""JsonFileBackend — default QueueBackend implementation.

Persists tasks to a single JSON file. CRITICAL invariants (from spec):
- Uses safe_write (NOT direct os.replace) so writes participate in the
  AtomicContext suspension/batching system.
- Filters out APPROVED tasks in snapshot() so already-terminal work
  does not re-appear on reload.
- Recovers gracefully from corrupt / empty / missing files.
"""
from __future__ import annotations
import json
import logging
from dataclasses import asdict
from pathlib import Path

from ..lib.write_hooks import safe_write
from ..types import KnowledgeTask, TaskStatus

logger = logging.getLogger(__name__)


class JsonFileBackend:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # Internal lock protects the in-memory snapshot during
        # enqueue/save. The QueueService holds a service-level lock
        # that covers multi-step orchestration; this lock only guards
        # the backend's own data structure for the unlikely case that
        # a future caller bypasses the service layer.
        import threading
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._load_unlocked()

    # --- internal helpers (called only while holding self._lock) ---

    def _load_unlocked(self) -> None:
        """Load tasks from disk. Corrupt/empty/missing file → empty dict."""
        if not self.path.exists():
            self._tasks = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[JsonFileBackend] queue file corrupt ({e}); starting empty")
            self._tasks = {}
            return
        if not isinstance(data, list):
            logger.warning("[JsonFileBackend] queue file did not contain a list; starting empty")
            self._tasks = {}
            return
        result: dict[str, dict] = {}
        for row in data:
            if isinstance(row, dict) and "id" in row:
                result[row["id"]] = row
        self._tasks = result

    def _save_unlocked(self) -> None:
        """Persist in-memory tasks to disk via safe_write. Caller holds lock."""
        rows = list(self._tasks.values())
        # CRITICAL: use safe_write (which itself does tmp+os.replace under
        # the hood, but is also AtomicContext-aware). Do NOT call os.replace
        # directly — that bypasses the AtomicContext batching system.
        safe_write(self.path, json.dumps(rows, ensure_ascii=False, indent=2))

    # --- QueueBackend protocol ---

    def enqueue(self, task: KnowledgeTask) -> None:
        with self._lock:
            self._tasks[task.id] = asdict(task)
            self._save_unlocked()

    def save(self, task: KnowledgeTask) -> None:
        with self._lock:
            self._tasks[task.id] = asdict(task)
            self._save_unlocked()

    def find(self, task_id: str) -> KnowledgeTask | None:
        with self._lock:
            row = self._tasks.get(task_id)
            if row is None:
                return None
            try:
                return KnowledgeTask(**row)
            except (TypeError, ValueError) as e:
                logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
                return None

    def snapshot(self) -> list[KnowledgeTask]:
        with self._lock:
            result: list[KnowledgeTask] = []
            for row in self._tasks.values():
                if row.get("status") == TaskStatus.APPROVED.value:
                    continue
                try:
                    result.append(KnowledgeTask(**row))
                except (TypeError, ValueError) as e:
                    logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
            return result
