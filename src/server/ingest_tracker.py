"""Ingest task lifecycle tracker.

Subscribes to event_bus and maintains an in-memory map of task_id → status
record so the web frontend can poll `GET /api/v1/projects/{id}/ingest/status/{task_id}`
to show progress for tasks that were just enqueued via POST /ingest.

Spec: FRONTEND_DESIGN.md §14.1.

Lifecycle:
  queued   — at TASK_CREATED (we set this ourselves; the enum uses "pending")
  running  — at first COLLECTOR_DONE / PROCESSOR_DONE / etc.
  succeeded / failed / dead_letter — at TASK_STATUS_CHANGED / TASK_DEAD_LETTER
"""
from __future__ import annotations

import threading
import time
from typing import Any

from ..events.event_bus import event_bus
from ..events.events import EventName

# task_id → record
_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_initialized = False


def _now_ms() -> int:
    return int(time.time() * 1000)


def init_tracker() -> None:
    """Subscribe handlers to event_bus. Idempotent (safe to call twice)."""
    global _initialized
    if _initialized:
        return

    def _on_collector_done(p: Any):
        _touch_stage(p, "collector")

    def _on_processor_done(p: Any):
        _touch_stage(p, "processor")

    def _on_librarian_done(p: Any):
        _touch_stage(p, "librarian")

    event_bus.on(EventName.TASK_CREATED, _on_created)
    event_bus.on(EventName.TASK_STATUS_CHANGED, _on_status)
    event_bus.on(EventName.TASK_DEAD_LETTER, _on_dead_letter)
    event_bus.on(EventName.COLLECTOR_DONE, _on_collector_done)
    event_bus.on(EventName.PROCESSOR_DONE, _on_processor_done)
    event_bus.on(EventName.LIBRARIAN_DONE, _on_librarian_done)

    _initialized = True


def _on_created(p: Any) -> None:
    task_id = getattr(p, "task_id", None)
    if not task_id:
        return
    with _lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "stages": [],
            "started_at": _now_ms(),
            "finished_at": None,
            "error": None,
            "project_id": getattr(p, "project_id", None),
        }


def _on_status(p: Any) -> None:
    task_id = getattr(p, "task_id", None)
    if not task_id:
        return
    with _lock:
        rec = _tasks.get(task_id)
        if rec is None:
            return
        to_status = getattr(p, "to_status", None)
        if to_status is not None:
            # Normalize enum to its string value
            rec["status"] = to_status.value if hasattr(to_status, "value") else str(to_status)
            if rec["status"] == "running" and "running_marked_at" not in rec:
                rec["running_marked_at"] = _now_ms()
        err = getattr(p, "error", None)
        if err:
            rec["error"] = err
        # Terminal statuses
        if rec["status"] in ("succeeded", "approved", "archived", "rejected"):
            rec["status"] = "succeeded"
            rec["finished_at"] = _now_ms()
        elif rec["status"] in ("failed", "timeout", "dead_letter"):
            rec["status"] = "failed"
            rec["finished_at"] = _now_ms()


def _on_dead_letter(p: Any) -> None:
    task_id = getattr(p, "task_id", None)
    if not task_id:
        return
    with _lock:
        rec = _tasks.get(task_id)
        if rec is None:
            return
        rec["status"] = "failed"
        rec["error"] = getattr(p, "error", None) or "dead letter"
        rec["finished_at"] = _now_ms()


def _touch_stage(p: Any, stage_name: str) -> None:
    task_id = getattr(p, "task_id", None)
    if not task_id:
        return
    with _lock:
        rec = _tasks.get(task_id)
        if rec is None:
            return
        # If still queued, advance to running on first stage event
        if rec["status"] == "queued":
            rec["status"] = "running"
        # Append stage event (allow duplicate stage names for repeated runs)
        rec["stages"].append({"name": stage_name, "at": _now_ms()})


def get_task(task_id: str) -> dict | None:
    """Return a copy of the record for task_id, or None if unknown."""
    with _lock:
        rec = _tasks.get(task_id)
        return dict(rec) if rec else None


def list_tasks(project_id: str | None = None) -> list[dict]:
    """Return all tracked tasks (optionally filtered by project_id)."""
    with _lock:
        items = list(_tasks.values())
    if project_id is not None:
        items = [t for t in items if t.get("project_id") == project_id]
    return [dict(t) for t in items]


def prune_finished(max_age_ms: int = 24 * 3600 * 1000) -> int:
    """Drop records for tasks that finished > max_age_ms ago. Returns count pruned."""
    cutoff = _now_ms() - max_age_ms
    pruned = 0
    with _lock:
        for tid in list(_tasks.keys()):
            t = _tasks[tid]
            if t.get("finished_at") and t["finished_at"] < cutoff:
                del _tasks[tid]
                pruned += 1
    return pruned
