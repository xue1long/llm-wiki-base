"""PipelineRunner — drives a sequence of PipelineStages.

The runner is the orchestrator. It takes a list of stages and a
PipelineContext, runs them in order, propagates results via the context,
and reports success/failure to the queue service (status transitions +
in-flight release).

Exception handling is centralized here: any stage that raises is caught,
the task is marked FAILED (with the retry policy deciding PENDING vs
DEAD_LETTER), and the in-flight flag is released.
"""
from __future__ import annotations
import logging
from typing import Sequence

from ..types import TaskStatus
from ..events.event_bus import event_bus
from ..events.events import EventName
from .ports import PipelineContext, PipelineStage, StageResult

_logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(self, queue_service) -> None:
        """queue_service is duck-typed: must have update_status(task_id, status, error)
        and release_in_flight(task_id)."""
        self.queue_service = queue_service

    async def run_stages(
        self,
        stages: Sequence[PipelineStage],
        ctx: PipelineContext,
    ) -> None:
        prev_result: StageResult | None = None
        try:
            for stage in stages:
                _logger.debug("Running stage %s for task %s", stage.name, ctx.task_id)
                event_bus.emit(EventName.STAGE_STARTED, {
                    "task_id": ctx.task_id,
                    "stage": stage.name,
                })
                result = await stage.run(ctx, prev_result)
                prev_result = result
                if not result.success:
                    raise RuntimeError(
                        f"Stage {stage.name} returned success=False: {result.payload}"
                    )
            # All stages succeeded
            self.queue_service.update_status(ctx.task_id, TaskStatus.APPROVED)
        except Exception as exc:
            _logger.exception("Pipeline failed for task %s", ctx.task_id)
            try:
                self.queue_service.update_status(
                    ctx.task_id, TaskStatus.FAILED, error=str(exc),
                )
            finally:
                self.queue_service.release_in_flight(ctx.task_id)
            return
        # Success path: release in-flight here
        self.queue_service.release_in_flight(ctx.task_id)
