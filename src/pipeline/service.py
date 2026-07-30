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
from .ingest import run_ingest
from .ports import PipelineContext, PipelineStage
from .runner import PipelineRunner
from .stages import AnalyzerStage, CollectorStage, GeneratorStage

_logger = logging.getLogger(__name__)

# Prevent flooding the LLM API with concurrent requests — MiniMax M3 in
# particular degrades under load (>3 concurrent calls).  Bump once the
# default provider supports higher concurrency.
DEFAULT_MAX_CONCURRENCY = 6


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

        async with self._semaphore:
            await self._run_for_collector_start_inner(task_id, source, source_type, project_id)

    async def _run_for_collector_start_inner(self, task_id, source, source_type, project_id) -> None:
        """Actual pipeline work — called while the semaphore is held."""

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
            return

        # Wrap the entire pipeline (collector + ingest) in a try/finally so
        # release_in_flight always runs — even if the collector raises an
        # unexpected exception (e.g. PermissionDenied on a mis-prefixed path).
        # Without this, a stuck in-flight marker blocks the queue permanently.
        try:
            # Step 1: Collector (read source)
            ctx = PipelineContext(
                task_id=task_id, source=source, source_type=source_type,
                project_id=project_id,
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

            # Step 2: Run the full ingest (analyze + generate + source page + atomic write)
            # This is the IO-heavy path from src/pipeline/pipeline.py:_on_collector_done
            # Late import: src.pipeline.pipeline may not be in sys.modules
            # yet at module-load time (the compat shim registration happens
            # during __init__.py). At call time, the shim is in place.
            import src.pipeline.pipeline as _pipeline_mod
            from pathlib import Path as _Path
            paths = _pipeline_mod._resolve_wiki_paths(project_id=project_id)
            provider = _pipeline_mod._get_provider(project_id=project_id)
            # raw_path is a str (CollectorDonePayload.raw_path). Wrap
            # in Path so run_ingest can call .suffix / .name on it.
            await _pipeline_mod.run_ingest(
                paths=paths,
                source_path=_Path(ctx.collector_result.raw_path),
                source_text=ctx.collector_result.content,
                provider=provider,
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