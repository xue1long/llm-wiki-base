"""QueueService — composition root for queue subsystem.

Holds the service-level lock that serializes all multi-step orchestration
(enqueue + save, snapshot + acquire + emit, update_status + save). The
default singleton is process-wide; tests construct instances directly
with FakeBackends.

Public API (re-exported from src/queue/__init__.py):
- enqueue_task
- update_task_status
- get_queue
- pause_queue
- resume_queue
- generate_task_id
- get_default_queue_service

Private (NOT re-exported):
- release_in_flight (consumed by src/pipeline/service.py)
- _advance, _persist (internal helpers)
"""
from __future__ import annotations
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from ..circuit_breaker import get_circuit_breaker
from ..events.event_bus import event_bus
from ..types import KnowledgeTask, SourceType, TaskStatus
from ..utils.idempotency import remove_hash
from .in_flight import InMemoryInFlightTracker
from .persistence import JsonFileBackend
from .ports import EventEmitter, InFlightTracker, QueueBackend, RetryPolicy
from .retry import MAX_RETRIES, DefaultRetryPolicy
from .scheduler import select_next_task
from .state import can_transition, InvalidTransition
from ..events.events import (
    EventName, TaskCreatedPayload, TaskStatusChangedPayload,
    TaskDeadLetterPayload,
)

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_NAME = "task_queue"
QUEUE_FILE = ".kb-queue.json"
PAUSE_FILE = ".kb-queue-paused"


def generate_task_id() -> str:
    unique_part = uuid.uuid4().hex[:8]
    return f"kb-{datetime.now().strftime('%Y%m%d%H%M%S')}-{unique_part}"


class QueueService:
    def __init__(
        self,
        backend: QueueBackend,
        tracker: InFlightTracker,
        emitter: EventEmitter,
        retry_policy: RetryPolicy,
        *,
        circuit_breaker_name: str = CIRCUIT_BREAKER_NAME,
    ) -> None:
        self.backend = backend
        self.tracker = tracker
        self.emitter = emitter
        self.retry_policy = retry_policy
        self._breaker_name = circuit_breaker_name
        self._service_lock = threading.Lock()
        self._paused = Path(PAUSE_FILE).exists()

    def _breaker(self):
        """Resolve the breaker each call — never cache the instance, since
        tests reset state in-place (see test_pipeline_event_bus_integration.py)."""
        return get_circuit_breaker(self._breaker_name)

    # --- public API ---

    def enqueue(
        self,
        source: str,
        source_type: SourceType,
        task_hash: str,
        project_id: str | None = None,
    ) -> str:
        task_id: str = ""   # assigned inside lock; always overwritten before use

        with self._service_lock:
            # Check persistent backend for existing tasks with the same hash.
            # Only treat as duplicate if there's a PENDING or RUNNING task.
            # FAILED/DEAD_LETTER tasks with the same hash can be re-enqueued.
            #
            # The duplicate check + removal + enqueue are all inside the same
            # lock so that concurrent callers cannot both see an empty result
            # and both enqueue (TOCTOU race, surfaced by
            # test_concurrent_enqueue_preserves_unique_tasks).
            existing = self.backend.find_by_hash(task_hash)
            active = [t for t in existing if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
            if active:
                logger.info(f"[Queue] Duplicate task_hash (active task exists): {task_hash}")
                return ""

            # Remove any terminal-state tasks with the same hash before enqueueing new one.
            for t in existing:
                self.backend.remove(t.id)

            task = KnowledgeTask(
                id=generate_task_id(),
                source=source,
                source_type=source_type,
                status=TaskStatus.PENDING,
                task_hash=task_hash,
                created_at=int(datetime.now().timestamp()),
                updated_at=int(datetime.now().timestamp()),
                retry_count=0,
                project_id=project_id,
            )
            self.backend.enqueue(task)
            task_id = task.id

        # Emit AFTER lock release (handler may re-enter the queue)
        self.emitter.emit(EventName.TASK_CREATED, TaskCreatedPayload(
            task_id=task_id,
            source=source,
            source_type=source_type,
            task_hash=task_hash,
            project_id=project_id,
        ))
        self.advance(prefer_task_id=task_id, project_id=project_id)
        return task_id

    def enqueue_batch(
        self,
        items: list[dict],
        project_id: str | None = None,
    ) -> list[str]:
        """Enqueue multiple sources in a single lock acquisition + single disk write.

        Each item is a dict with keys: source, source_type, task_hash.

        Does NOT emit TASK_CREATED or call advance() per-item. The caller
        should call advance() a few times afterward to kick off processing.
        """
        task_ids: list[str] = []
        with self._service_lock:
            tasks_to_add: list[KnowledgeTask] = []
            for item in items:
                source = item["source"]
                source_type = item["source_type"]
                task_hash = item["task_hash"]

                existing = self.backend.find_by_hash(task_hash)
                active = [t for t in existing if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
                if active:
                    continue
                for t in existing:
                    self.backend.remove(t.id)

                task = KnowledgeTask(
                    id=generate_task_id(),
                    source=source,
                    source_type=source_type,
                    status=TaskStatus.PENDING,
                    task_hash=task_hash,
                    created_at=int(datetime.now().timestamp()),
                    updated_at=int(datetime.now().timestamp()),
                    retry_count=0,
                    project_id=project_id,
                )
                tasks_to_add.append(task)
                task_ids.append(task.id)

            if tasks_to_add:
                self.backend.enqueue_batch(tasks_to_add)

        return task_ids

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        """Update a task after validating the state-machine transition.

        May call advance() (under retry) — that's why emit and advance are
        done OUTSIDE the lock.
        """
        breaker = self._breaker()
        dead_letter_payload = None
        retry_will_resume = False
        prev_status: TaskStatus
        emit_status: TaskStatus
        emit_payload: TaskStatusChangedPayload

        with self._service_lock:
            task = self.backend.find(task_id)
            if task is None:
                raise KeyError(task_id)

            prev_status = task.status
            if not can_transition(prev_status, status):
                raise InvalidTransition(task_id, prev_status.value, status.value)

            decision = self.retry_policy.decide(task, status, error, breaker)
            task.status = decision.new_status
            task.updated_at = int(datetime.now().timestamp())
            if error is not None:
                task.error = error

            if decision.should_record_breaker_failure:
                breaker.record_failure()

            if decision.should_pause_queue:
                self._paused = True
                logger.warning("[Queue] Queue paused due to repeated failures")

            if decision.new_status == TaskStatus.DEAD_LETTER:
                dead_letter_payload = TaskDeadLetterPayload(
                    task_id=task_id,
                    retry_count=task.retry_count,
                    error=task.error or error or "",
                )
                logger.warning(
                    f"[Queue] Task {task_id} exceeded max retries, moving to dead letter"
                )
                # Allow re-enqueue of the same source after dead-letter.
                remove_hash(task.task_hash)

            if decision.new_status == TaskStatus.FAILED:
                # Allow re-enqueue of the same source after failure.
                remove_hash(task.task_hash)

            if decision.new_status == TaskStatus.PENDING:
                retry_will_resume = True
                # Release the in-flight marker so the post-retry advance()
                # call can re-dispatch the same task. The previous (pre-
                # service) implementation left the marker set, which forced
                # callers to manually discard the in-flight id before the
                # retry could re-dispatch.
                self.tracker.release(task_id)

            self.backend.save(task)
            emit_status = decision.new_status
            emit_payload = TaskStatusChangedPayload(
                task_id=task_id,
                from_status=prev_status,
                to_status=emit_status,
                error=error,
            )

        # Outside the lock
        self.emitter.emit(EventName.TASK_STATUS_CHANGED, emit_payload)
        if dead_letter_payload is not None:
            self.emitter.emit(EventName.TASK_DEAD_LETTER, dead_letter_payload)
        if retry_will_resume:
            self.advance()

    def advance(
        self,
        *,
        prefer_task_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Try to pick and dispatch one task. Returns True if dispatched."""
        task: KnowledgeTask | None
        payload: dict
        with self._service_lock:
            if self._paused:
                return False
            if not self._breaker().can_execute():
                logger.warning(
                    f"[Queue] Circuit breaker is {self._breaker().state.value}, skipping"
                )
                return False

            task = select_next_task(
                self.backend, self.tracker, prefer_task_id=prefer_task_id,
            )
            if task is None:
                return False
            if not self.tracker.acquire(task.id):
                return False

            effective_project_id = project_id or task.project_id
            payload = {
                "task_id": task.id,
                "source": task.source,
                "source_type": task.source_type,
            }
            if effective_project_id is not None:
                payload["project_id"] = effective_project_id

        # Outside the lock — emit
        self.emitter.emit("collector:start", payload)
        return True

    def pause(self) -> None:
        with self._service_lock:
            self._paused = True
            Path(PAUSE_FILE).write_text("1")
            logger.warning("[Queue] Queue paused (persisted)")

    def resume(self) -> None:
        with self._service_lock:
            self._paused = False
            try:
                Path(PAUSE_FILE).unlink(missing_ok=True)
            except OSError:
                pass
            self._breaker().record_success()
            logger.info("[Queue] Queue resumed (persisted)")
        self.advance()

    def release_in_flight(self, task_id: str) -> None:
        """Release a task after its pipeline reaches a terminal state.

        If the task is still in RUNNING state (pipeline crashed without calling
        update_status), move it to PENDING so the scheduler can retry it.
        This handles the case where a pipeline run raises an exception after
        the collector starts but before the generator completes.

        Only calls advance() when the in-flight marker was still held at entry.
        When update_status already handled a FAILED→PENDING retry (which
        releases the in-flight marker + calls advance() internally), the marker
        is already clear — skipping the redundant advance() here prevents a
        double-dispatch of the same task.
        """
        with self._service_lock:
            was_in_flight = self.tracker.is_in_flight(task_id)
            self.tracker.release(task_id)
            task = self.backend.find(task_id)
            if task is not None and task.status == TaskStatus.RUNNING:
                # Pipeline exited abnormally (crashed / timed out) without
                # calling update_status — put it back to PENDING for retry.
                # Only retry if attempts remain; otherwise leave RUNNING
                # so the caller can mark DEAD_LETTER.
                if task.retry_count < MAX_RETRIES:
                    task.status = TaskStatus.PENDING
                    task.updated_at = int(datetime.now().timestamp())
                    self.backend.save(task)
                    logger.info(
                        "[Queue] Task %s released in-flight but still RUNNING — "
                        "reset to PENDING for retry (%d/%d attempts)",
                        task_id, task.retry_count, MAX_RETRIES,
                    )
                else:
                    logger.warning(
                        "[Queue] Task %s released in-flight with max retries "
                        "exhausted, leaving RUNNING for caller to mark DEAD_LETTER",
                        task_id,
                    )
        if was_in_flight:
            self.advance()

    def get_queue(self) -> list[KnowledgeTask]:
        # Return all tasks (including APPROVED / DEAD_LETTER). The
        # snapshot-based view is used internally by select_next_task to
        # find pending work; ``get_queue`` is the public inspection API
        # and must show every task, including ones that have already
        # reached a terminal state. (Tests rely on this; production
        # code paths that want only pending tasks should call
        # ``backend.snapshot()`` directly or ``select_next_task``.)
        with self._service_lock:
            return [
                task
                for task in (self.backend.find(tid) for tid in self.backend.iter_ids())
                if task is not None
            ]

    def get_status(self) -> dict:
        breaker = self._breaker()
        tasks = self.get_queue()
        with self._service_lock:
            return {
                "paused": self._paused,
                "circuit_breaker_state": breaker.state.value,
                "failure_count": breaker.failure_count,
                "pending_count": len([t for t in tasks if t.status == TaskStatus.PENDING]),
                "running_count": len([t for t in tasks if t.status == TaskStatus.RUNNING]),
                "failed_count": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            }


# --- module-level default service singleton ---

_default_service: QueueService | None = None
_default_lock = threading.Lock()


def get_default_queue_service() -> QueueService:
    global _default_service
    with _default_lock:
        if _default_service is None:
            from pathlib import Path
            _default_service = QueueService(
                backend=JsonFileBackend(Path(QUEUE_FILE)),
                tracker=InMemoryInFlightTracker(),
                emitter=event_bus,
                retry_policy=DefaultRetryPolicy(),
            )
        return _default_service


def __reset_for_testing() -> None:
    """Test-only: discard the default singleton AND wipe the persisted
    queue file so the next call to get_default_queue_service() rebuilds
    against an empty state.

    Without the disk clear, tests that expect ``get_queue()[0]`` to
    return their own enqueued task see stale tasks from prior tests
    that have already been persisted. (The original src/queue/queue.py
    had the same singleton-rebuild behaviour but the legacy tests
    didn't need a clean disk because they all used the same queue file
    and treated stale entries as expected — the refactored service
    surfaces them through get_queue(), so test isolation now requires
    the disk to be clean.)
    """
    global _default_service
    with _default_lock:
        _default_service = None
    # Clear the persisted queue file so the new singleton starts empty.
    try:
        from pathlib import Path
        Path(QUEUE_FILE).unlink(missing_ok=True)
    except OSError:
        pass
