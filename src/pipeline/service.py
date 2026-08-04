"""PipelineService — composition root for the pipeline subsystem.

Owns the PipelineRunner, the registered stages, and the queue service
(the source of update_status / release_in_flight). The default singleton
is process-wide; tests construct instances directly.

Public methods:
- register_stages(stages): set the list of stages to run per pipeline
- run_for_collector_start(payload): the async entry point called by
  the dispatcher when an EventBus "collector:start" event fires
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Sequence

from ..queue.service import get_default_queue_service
from ..types import SourceType, TaskStatus
# NOTE: `src.pipeline.pipeline` (the compat shim) is NOT imported at module
# top — it triggers a circular import because `__init__.py` hasn't
# finished registering the shim when this service module loads. Instead,
# the compat shim is resolved lazily inside run_for_collector_start via
# ``import src.pipeline.pipeline as _pipeline_mod`` (inside the function).
# By call time, `__init__.py` has finished and the shim is in place.
from .dispatcher import dispatch_collector_start
from .ports import PipelineContext, PipelineStage
from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage

_logger = logging.getLogger(__name__)

# Prevent flooding the LLM API with concurrent requests.
# Default: 6 (safe for most providers).
# MiniMax users should set RUFLO_LLM_MAX_CONCURRENCY=3
# OpenAI/Anthropic users can set RUFLO_LLM_MAX_CONCURRENCY=15-20
DEFAULT_MAX_CONCURRENCY = int(os.environ.get("RUFLO_LLM_MAX_CONCURRENCY", "6"))

# Rollback switch: when false, use legacy pipeline path.
# When true (default), use the new stage-scheduler path with Candidate/Reviewer/Promoter.
USE_STAGE_SCHEDULER = os.environ.get("RUFLO_USE_STAGE_SCHEDULER", "true").lower() == "true"


class PipelineService:
    def __init__(self, queue_service=None, max_concurrency: int = DEFAULT_MAX_CONCURRENCY) -> None:
        # Hold a callable (not an instance) so the queue service is looked
        # up fresh on every chain run. This keeps the pipeline service
        # compatible with tests that call ``__reset_for_testing`` to drop
        # the queue singleton — without late binding, the pipeline would
        # keep using a stale backend and ``update_status(task_id, ...)``
        # would raise KeyError.
        self._queue_service_factory = queue_service or get_default_queue_service
        self._semaphore = asyncio.Semaphore(max_concurrency)
        # Cache the runner with the initial queue service; on the next
        # chain run we'll resolve the factory again.
        self.runner = PipelineRunner(self._queue_service_factory())
        self._stages: list[PipelineStage] = [
            CollectorStage(), AnalyzerStage(), GeneratorStage(),
        ]

    @property
    def queue_service(self):
        return self._queue_service_factory()

    def register_stages(self, stages: Sequence[PipelineStage]) -> None:
        self._stages = list(stages)

    async def run_for_collector_start(self, payload: dict) -> None:
        """Drive the full pipeline chain for a "collector:start" event.

        payload is a dict with keys: task_id, source, source_type, project_id.

        Guarded by an ``asyncio.Semaphore`` so at most *max_concurrency*
        LLM calls are in-flight at once.
        """
        task_id = payload["task_id"]
        source = payload["source"]
        source_type = payload.get("source_type", SourceType.FILE)
        project_id = payload.get("project_id")
        folder_context = payload.get("folder_context")

        async with self._semaphore:
            await self._run_for_collector_start_inner(task_id, source, source_type, project_id,
                                                       folder_context=folder_context)

    async def _run_for_collector_start_inner(self, task_id, source, source_type, project_id,
                                              folder_context: str | None = None) -> None:
        """Actual pipeline work — called while the semaphore is held."""

        # Acquire project lock to prevent concurrent ingest on same project
        from ..queue.distributed_lock import get_project_lock, LockHeldError
        project_lock = get_project_lock()
        lock_acquired = False

        try:
            await project_lock.acquire(project_id or "default")
            lock_acquired = True
        except LockHeldError as e:
            _logger.warning(
                "[PipelineService] Project %s locked by another process, requeueing task %s",
                project_id, task_id
            )
            # Re-queue the task for later processing
            # Note: task is still PENDING at this point, so we only update
            # the error message without changing status (PENDING→PENDING is invalid)
            try:
                task = self.queue_service.backend.find(task_id)
                if task is not None and task.status != TaskStatus.PENDING:
                    self.queue_service.update_status(
                        task_id, status=TaskStatus.PENDING,
                        error=f"Project locked, will retry: {e}",
                    )
                # If already PENDING, just release the in-flight marker
            except Exception:
                _logger.exception("failed to update task %s for lock error", task_id)
            finally:
                try:
                    self.queue_service.release_in_flight(task_id)
                except Exception:
                    _logger.exception("failed to release_in_flight %s", task_id)
            return
        except Exception as e:
            _logger.warning(
                "[PipelineService] Failed to acquire project lock: %s, proceeding without lock",
                e
            )
            # Proceed without lock (fallback for single-instance deployments)

        # Mirror the original pipeline.py behavior: mark RUNNING before
        # touching any IO. PENDING -> APPROVED is an illegal transition
        # under the state machine; PENDING -> RUNNING -> APPROVED is legal.
        try:
            self.queue_service.update_status(task_id, status=TaskStatus.RUNNING)
        except Exception:
            _logger.exception("failed to mark %s RUNNING", task_id)
            try:
                self.queue_service.release_in_flight(task_id)
            except Exception:
                _logger.exception("failed to release_in_flight %s", task_id)
            if lock_acquired:
                await project_lock.release(project_id or "default")
            return

        # Wrap the entire pipeline (collector + ingest) in a try/finally so
        # release_in_flight always runs — even if the collector raises an
        # unexpected exception (e.g. PermissionDenied on a mis-prefixed path).
        # Without this, a stuck in-flight marker blocks the queue permanently.
        try:
            # Late import: resolve paths/provider before ctx construction
            import src.pipeline.pipeline as _pipeline_mod
            from pathlib import Path as _Path
            paths = _pipeline_mod._resolve_wiki_paths(project_id=project_id)
            provider = _pipeline_mod._get_provider(project_id=project_id)

            # Step 1: Collector (read source)
            ctx = PipelineContext(
                task_id=task_id, source=source, source_type=source_type,
                project_id=project_id, paths=paths, provider=provider,
            )
            for stage in self._stages[:1]:  # only CollectorStage
                result = await stage.run(ctx, prev_result=None)
                if not result.success:
                    self.queue_service.update_status(
                        task_id, status=TaskStatus.FAILED,
                        error=f"collector stage failed: {result.payload}",
                    )
                    return
                ctx.collector_result = result.payload

            # Choose pipeline path based on rollback switch
            if USE_STAGE_SCHEDULER:
                # New path: run full stage chain (Analyzer → Reviewer → Promoter → Generator → Committer)
                await self._run_stage_chain(ctx, folder_context)
            else:
                # Legacy path: run_ingest (analyze + generate + source page + atomic write)
                # raw_path is a str (CollectorDonePayload.raw_path). Wrap
                # in Path so run_ingest can call .suffix / .name on it.
                await _pipeline_mod.run_ingest(
                    paths=paths,
                    source_path=_Path(ctx.collector_result.raw_path),
                    source_text=ctx.collector_result.content,
                    provider=provider,
                    folder_context=folder_context or "",
                    task_id=task_id,
                )
            self.queue_service.update_status(task_id, status=TaskStatus.APPROVED)
        except Exception as exc:
            _logger.exception("ingest failed for %s", task_id)
            try:
                self.queue_service.update_status(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(exc),
                )
            except Exception:
                _logger.exception("failed to update_status to FAILED for %s", task_id)
        finally:
            try:
                self.queue_service.release_in_flight(task_id)
            except Exception:
                _logger.exception("failed to release_in_flight %s", task_id)
            # Release project lock
            if lock_acquired:
                try:
                    await project_lock.release(project_id or "default")
                except Exception as e:
                    _logger.warning("failed to release project lock for %s: %s", project_id, e)

    async def _run_stage_chain(self, ctx: PipelineContext, folder_context: str | None = None) -> None:
        """Run the full stage chain: Analyzer → Reviewer → Promoter → Generator → Committer."""
        from .stages import AnalyzerStage, ReviewerStage, CandidatePromoter, GeneratorStage, CommitStage

        ctx.folder_context = folder_context or ""
        ctx.source_path = ctx.collector_result.raw_path

        stages = [
            AnalyzerStage(),
            ReviewerStage(),
            CandidatePromoter(),
            GeneratorStage(),
            CommitStage(),
        ]

        prev_result = ctx.collector_result  # Start with CollectorDonePayload
        for stage in stages:
            result = await stage.run(ctx, prev_result)
            if not result.success:
                raise RuntimeError(f"Stage {stage.name} failed: {result.payload}")
            prev_result = result


# --- module-level default singleton ---

_default_service: PipelineService | None = None


def get_default_pipeline_service() -> PipelineService:
    global _default_service
    if _default_service is None:
        _default_service = PipelineService()
    return _default_service


# --- explicit event registration ---

_registered = False


def register_stages(stages: Sequence[PipelineStage]) -> None:
    """Register the pipeline stages. Idempotent — safe to call multiple times."""
    get_default_pipeline_service().register_stages(stages)
    _register_event_handlers()


def _register_event_handlers() -> None:
    """Bind dispatcher to EventBus. Called from __init__.py on import."""
    from ..events.event_bus import event_bus
    global _registered
    if _registered:
        return
    _registered = True
    # Lazily resolve PipelineService so tests that call __reset_for_testing
    # see the new singleton rather than a stale closure reference.
    event_bus.on("collector:start", lambda payload: dispatch_collector_start(get_default_pipeline_service(), payload))
