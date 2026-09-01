"""Tests for the pipeline dispatcher's stale-RUNNING recovery path.

Pre-PR-1 bug: when a server restart occurred while a task was RUNNING,
the new process picked the task (the in-memory in-flight tracker starts
empty), the dispatcher tried ``update_status(RUNNING)``, and the state
matrix raised ``InvalidTransition`` (``RUNNING→RUNNING`` is illegal).
The dispatcher's except handler logged + called ``release_in_flight``
but ``was_in_flight=False`` (fresh tracker) so the advance at the end was
skipped — the task sat RUNNING forever (until the snapshot 10-minute
stale-reset kicked in).

After PR-1:
* The dispatcher peeks at the persisted state BEFORE calling
  ``update_status(RUNNING)``. If the task is already RUNNING, it routes
  through ``release_in_flight`` which (after PR-1) correctly counts the
  crash as one attempt and dead-letters after MAX_RETRIES crashes.
* ``release_in_flight`` itself increments retry_count on every crash
  reset, eliminating the previous infinite-loop hazard.
"""

from __future__ import annotations

import pytest

from src.queue import (
    __reset_for_testing,
    enqueue_task,
    get_default_queue_service,
)
from src.queue.retry import MAX_RETRIES
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache

from src.pipeline.service import PipelineService


def setup_function(_):
    get_idempotency_cache().clear()
    __reset_for_testing()
    svc = get_default_queue_service()
    svc.pause()
    # Reset the queue circuit breaker.
    from src.circuit_breaker import get_circuit_breaker, CircuitState
    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0


def _force_persisted_running(task_id: str) -> None:
    """Simulate the post-crash state: a previous process died with the
    task RUNNING on disk, in-flight tracker empty (fresh process)."""
    svc = get_default_queue_service()
    task = svc.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    svc.backend.save(task)


@pytest.mark.asyncio
async def test_dispatcher_recovers_from_persisted_running(tmp_path, monkeypatch):
    """The dispatcher must NOT throw InvalidTransition when re-dispatching
    a task that was RUNNING on disk at process start. The stale-RUNNING
    guard routes through release_in_flight."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("stale.md", SourceType.FILE, "hash-stale")

    # Simulate: previous process crashed mid-pipeline.
    _force_persisted_running(task_id)

    # Fresh in-flight tracker (simulating fresh process boot).
    assert task_id not in svc.tracker.snapshot()

    # The dispatcher would pick this task via select_next_task → acquire,
    # then call _run_for_collector_start_inner. We mimic that path
    # directly: acquire the tracker (simulating select_next_task), then
    # invoke the inner.
    svc.tracker.acquire(task_id)

    ps = PipelineService()
    await ps._run_for_collector_start_inner(
        task_id=task_id, source="stale.md",
        source_type=SourceType.FILE, project_id=None,
    )

    # The stale-RUNNING branch must have routed through release_in_flight,
    # which counts the crash and resets to PENDING (still under MAX_RETRIES).
    task = svc.backend.find(task_id)
    assert task.status is TaskStatus.PENDING, (
        f"stale-RUNNING recovery should reset to PENDING, got {task.status}"
    )
    assert task.retry_count == 1, (
        f"recovery should count as one attempt, got retry_count={task.retry_count}"
    )


@pytest.mark.asyncio
async def test_dispatcher_recovers_then_dead_letters_at_max_retries(tmp_path, monkeypatch):
    """If the same task is recovered from RUNNING repeatedly (every restart
    before crash-recovery matters), after MAX_RETRIES crashes the task
    must end up in DEAD_LETTER — not loop forever."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("loop.md", SourceType.FILE, "hash-loop-stale")

    ps = PipelineService()

    for expected_attempts in range(1, MAX_RETRIES + 2):
        # Simulate a crashed previous process.
        _force_persisted_running(task_id)
        svc.tracker.acquire(task_id)

        await ps._run_for_collector_start_inner(
            task_id=task_id, source="loop.md",
            source_type=SourceType.FILE, project_id=None,
        )

        task = svc.backend.find(task_id)
        if task.status is TaskStatus.DEAD_LETTER:
            assert task.retry_count >= MAX_RETRIES
            return  # Successful exhaustion.
        # Otherwise the recovery reset it to PENDING. Loop continues to
        # simulate next restart.
        assert task.status is TaskStatus.PENDING
        # Simulate that the in-flight tracker is reset between processes.
        svc.tracker.release(task_id)

    # Exhaustion did not occur within MAX_RETRIES+1 attempts.
    raise AssertionError(
        f"after {MAX_RETRIES + 1} stale-RUNNING recoveries, task "
        f"should be DEAD_LETTER, got status={svc.backend.find(task_id).status}"
    )


@pytest.mark.asyncio
async def test_dispatcher_does_not_recover_pending_tasks(tmp_path, monkeypatch):
    """Sanity guard: PENDING tasks must NOT trigger the stale-RUNNING
    branch — they must proceed through the normal collector pipeline
    path."""
    monkeypatch.chdir(tmp_path)
    svc = get_default_queue_service()
    task_id = enqueue_task("fresh.md", SourceType.FILE, "hash-fresh")

    # Sanity: task starts PENDING.
    assert svc.backend.find(task_id).status is TaskStatus.PENDING

    svc.tracker.acquire(task_id)

    # Spy on update_status to verify the dispatcher called it with RUNNING
    # (the stale-RUNNING short-circuit would skip that call).
    calls: list[tuple[str, TaskStatus]] = []
    original_update = svc.update_status

    def spy_update(tid, status, error=None):
        calls.append((tid, status))
        return original_update(tid, status, error=error)

    monkeypatch.setattr(svc, "update_status", spy_update)

    # Build a minimal PipelineService whose collector stage returns a
    # fake successful result without touching the filesystem.
    class _StubResult:
        def __init__(self, success, payload):
            self.success = success
            self.payload = payload

    class _StubPayload:
        def __init__(self):
            self.raw_path = "fresh.md"
            self.content = "x"
            self.artifact = None

    class _StubCollector:
        name = "collector"

        async def run(self, ctx, prev_result):
            return _StubResult(True, _StubPayload())

    ps = PipelineService()
    ps.register_stages([_StubCollector()])

    # Patch _resolve_wiki_paths + _get_provider + run_ingest so the dispatcher's
    # second step doesn't try to do real work.
    import src.pipeline.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod, "_get_provider", lambda project_id=None: object())

    async def stub_run_ingest(**kwargs):
        return []

    monkeypatch.setattr(pipeline_mod, "run_ingest", stub_run_ingest)

    await ps._run_for_collector_start_inner(
        task_id=task_id, source="fresh.md",
        source_type=SourceType.FILE, project_id=None,
    )

    # The normal path was taken — update_status(RUNNING) was called.
    assert any(status is TaskStatus.RUNNING for _, status in calls), (
        f"normal pipeline did not call update_status(RUNNING): {calls}"
    )
    # Stale-RUNNING branch did NOT short-circuit; the task transitioned
    # all the way to APPROVED via the stub ingest.
    final_status = svc.backend.find(task_id).status
    assert final_status is TaskStatus.APPROVED, (
        f"normal path did not complete (status={final_status})"
    )
