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
from pathlib import Path

from ..utils.path import safe_resolve

from ..lib.write_hooks import safe_write
from ..types import KnowledgeTask, TaskStatus

logger = logging.getLogger(__name__)


class JsonFileBackend:
    def __init__(self, path: Path) -> None:
        # Store the raw string so re-resolving on each write picks up
        # CWD changes (the legacy queue.py used a module-level constant
        # that safe_write resolved relative to CWD at write time).
        self._path = Path(path) if isinstance(path, Path) else path
        # Internal lock protects the in-memory snapshot during
        # enqueue/save. The QueueService holds a service-level lock
        # that covers multi-step orchestration; this lock only guards
        # the backend's own data structure for the unlikely case that
        # a future caller bypasses the service layer.
        import threading
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}
        self._load_unlocked()

    @property
    def path(self) -> Path:
        """Return the absolute, CWD-resolved path used for IO.

        Re-resolves the stored path on every access so that a
        monkeypatch.chdir() between construction and write picks up
        the new CWD (the legacy queue.py relied on safe_write
        resolving the relative constant at write time).
        """
        p = Path(self._path)
        if not p.is_absolute():
            p = safe_resolve(p)
        return p

    # --- internal helpers (called only while holding self._lock) ---

    def _load_unlocked(self) -> None:
        """Load tasks from disk. Corrupt/empty/missing file → empty dict."""
        if not self.path.exists():
            self._tasks = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
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
                # Coerce JSON-string enums back to their enum objects.
                # json.dumps serialises enum values to their .value (a str),
                # so the on-disk shape has "status": "pending", not the
                # enum object. Without this coercion, KnowledgeTask(**row)
                # stores raw strings in fields typed as enums, breaking
                # equality checks like `task.status is TaskStatus.APPROVED`
                # and comparisons against TaskStatus.PENDING in
                # select_next_task.
                if "status" in row and isinstance(row["status"], str):
                    try:
                        row["status"] = TaskStatus(row["status"])
                    except ValueError:
                        logger.warning("[JsonFileBackend] invalid status %r for task %r; skipping", row.get("status"), row.get("id"))
                        continue  # skip malformed row entirely
                if "source_type" in row and isinstance(row["source_type"], str):
                    from ..types import SourceType
                    try:
                        row["source_type"] = SourceType(row["source_type"])
                    except ValueError:
                        logger.warning("[JsonFileBackend] invalid source_type %r for task %r; skipping", row.get("source_type"), row.get("id"))
                        continue
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
            self._tasks[task.id] = task.to_dict()
            self._save_unlocked()

    def enqueue_batch(self, tasks: list[KnowledgeTask]) -> None:
        """Add multiple tasks and persist once. Much faster than per-task enqueue."""
        if not tasks:
            return
        with self._lock:
            for task in tasks:
                self._tasks[task.id] = task.to_dict()
            self._save_unlocked()

    def save(self, task: KnowledgeTask) -> None:
        with self._lock:
            self._tasks[task.id] = task.to_dict()
            self._save_unlocked()

    def find(self, task_id: str) -> KnowledgeTask | None:
        with self._lock:
            row = self._tasks.get(task_id)
            if row is None:
                return None
            try:
                return KnowledgeTask.from_dict(row)
            except (TypeError, ValueError) as e:
                logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
                return None

    def find_by_hash(self, task_hash: str) -> list[KnowledgeTask]:
        with self._lock:
            result: list[KnowledgeTask] = []
            for row in self._tasks.values():
                if row.get("task_hash") != task_hash:
                    continue
                try:
                    result.append(KnowledgeTask.from_dict(row))
                except (TypeError, ValueError) as e:
                    logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
            return result

    def remove(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save_unlocked()

    def iter_ids(self) -> list[str]:
        with self._lock:
            return list(self._tasks.keys())

    def snapshot(self, *, in_flight_ids: set[str] | None = None) -> list[KnowledgeTask]:
        import time
        _in_flight = in_flight_ids or set()
        with self._lock:
            result: list[KnowledgeTask] = []
            now = time.time()
            for row in self._tasks.values():
                if row.get("status") == TaskStatus.APPROVED.value:
                    continue
                # Reset stale RUNNING tasks to PENDING so the scheduler can
                # re-dispatch them. A task is stale if it has been RUNNING for
                # more than 10 minutes without reaching a terminal state — it
                # means the pipeline exited abnormally (crashed / was killed)
                # without calling update_status. The QueueService.retry path
                # already handles this via release_in_flight, but after a
                # server restart those in-memory markers are gone; snapshot()
                # is the only place that can recover them.
                #
                # CRITICAL: skip stale recovery for tasks that are currently
                # in-flight. The pipeline may still be running (slow LLM call,
                # large document); resetting RUNNING→PENDING while the task is
                # still active causes an InvalidTransition when the pipeline
                # later tries to mark it APPROVED (PENDING→APPROVED is illegal).
                if row.get("status") == TaskStatus.RUNNING.value:
                    if row["id"] in _in_flight:
                        # Task is in-flight — the pipeline is still running.
                        # Do NOT touch it. The in-flight marker was cleared
                        # by the stale check guard in release_in_flight already.
                        pass
                    else:
                        updated_at = row.get("updated_at", 0)
                        if now - updated_at > 600:  # 10 minutes
                            row["status"] = TaskStatus.PENDING
                            self._tasks[row["id"]] = row
                            self._save_unlocked()
                            logger.info(
                                "[JsonFileBackend] task %s was stale RUNNING, "
                                "reset to PENDING", row["id"],
                            )
                            continue
                try:
                    result.append(KnowledgeTask.from_dict(row))
                except (TypeError, ValueError) as e:
                    logger.warning(f"[JsonFileBackend] task row malformed ({e}); skipping")
            return result
