"""CollectorStage — wraps the existing `collect` function from
src/pipeline/collector.py as a PipelineStage.

Behavior is identical to calling `collect(task_id, source, source_type,
project_id=...)` directly. The stage's `run` is async, so it can be
awaited by the runner.
"""
from __future__ import annotations

from ..ports import PipelineContext, StageResult


class CollectorStage:
    name = "collector"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        # Import the actual collect function lazily so monkey-patching
        # (see tests/test_pipeline/test_pipeline_event_bus_integration.py)
        # continues to work: the test patches `pipeline_mod.collect`, and
        # we resolve the symbol at call time, not import time.
        #
        # Late import (inside run, not at module top) also avoids a
        # circular import: at module-load time, src.pipeline.pipeline may
        # not be registered yet as the compat shim — sys.modules will
        # contain the legacy pipeline.py module, breaking the shim
        # contract.
        import src.pipeline.pipeline as _pipeline_mod
        collect_fn = _pipeline_mod.collect
        payload = await collect_fn(
            ctx.task_id, ctx.source, ctx.source_type, project_id=ctx.project_id,
        )
        ctx.collector_result = payload
        return StageResult(success=True, payload=payload)
