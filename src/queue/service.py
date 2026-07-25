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

from ..circuit_breaker import get_circuit_breaker
from ..events.event_bus import event_bus
from ..types import KnowledgeTask, SourceType, TaskStatus
from ..utils.idempotency import check_duplicate
from .in_flight import InMemoryInFlightTracker
from .persistence import JsonFileBackend
from .ports import EventEmitter, InFlightTracker, QueueBackend, RetryPolicy
from .retry import DefaultRetryPolicy
from .scheduler import select_next_task
from .state import can_transition, InvalidTransition
from ..events.events import (
    EventName, TaskCreatedPayload, TaskStatusChangedPayload,
)

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_NAME = "task_queue"
QUEUE_FILE = ".kb-queue.json"


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
        self._paused = False

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
        if check_duplicate(task_hash):
            logger.info(f"[Queue] Duplicate task_hash: {task_hash}")
            return ""

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

        with self._service_lock:
            self.backend.enqueue(task)

        # Emit AFTER lock release (handler may re-enter the queue)
        self.emitter.emit(EventName.TASK_CREATED, TaskCreatedPayload(
            task_id=task.id,
            source=task.source,
            source_type=task.source_type,
            task_hash=task.task_hash,
            project_id=project_id,
        ))
        self.advance(prefer_task_id=task.id, project_id=project_id)
        return task.id

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
                dead_letter_payload = {
                    "task_id": task_id,
                    "retry_count": task.retry_count,
                    "last_error": task.error or error or "",
                }
                logger.warning(
                    f"[Queue] Task {task_id} exceeded max retries, moving to dead letter"
                )

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
            logger.warning("[Queue] Queue paused")

    def resume(self) -> None:
        with self._service_lock:
            self._paused = False
            self._breaker().record_success()
            logger.info("[Queue] Queue resumed")
        self.advance()

    def release_in_flight(self, task_id: str) -> None:
        """Release a task after its pipeline reaches a terminal state."""
        with self._service_lock:
            self.tracker.release(task_id)
        self.advance()

    def get_queue(self) -> list[KnowledgeTask]:
        with self._service_lock:
            return self.backend.snapshot()

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
    """Test-only: discard the default singleton so the next call to
    get_default_queue_service() rebuilds it from the current disk state.

    This replaces the old src/queue/queue.py:281-285 __reset_for_testing.
    The default service's tracker is reset to empty; the backend re-reads
    from disk on next access (its in-memory state is reloaded by the
    singleton's first enqueue/find).
    """
    global _default_service
    with _default_lock:
        _default_service = None
