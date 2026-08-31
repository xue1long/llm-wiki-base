"""AnalyzerStage — wraps `analyze` as a PipelineStage."""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import analyzer as _analyzer_module
from ..extraction_types import artifact_from_text
from ..readiness_gate import apply_readiness_gate, route_after_readiness
from ..text_preprocessing import PipelineDisposition


class AnalyzerStage:
    name = "analyzer"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if ctx.collector_result is None:
            return StageResult(success=False, payload="missing collector result")
        artifact = getattr(ctx.collector_result, "artifact", None)
        if artifact is None:
            source_id = getattr(ctx.collector_result, "raw_path", None) or ctx.source
            artifact = artifact_from_text(
                ctx.collector_result.content,
                source_id=source_id,
                format="md",
                extraction_method="native_text",
            )
        readiness = apply_readiness_gate(artifact)
        ctx.readiness_result = readiness
        disposition = await route_after_readiness(
            readiness, provider=ctx.provider, paths=ctx.paths, task_id=ctx.task_id
        )
        if disposition is not PipelineDisposition.CONTINUE:
            return StageResult(success=False, payload=readiness)
        analyze_fn = _analyzer_module.analyze
        analysis = await analyze_fn(
            source_text=ctx.collector_result.content,
            source_ext=ctx.source_path or "",
            existing_wiki_index="",
            folder_context=ctx.folder_context,
            provider=ctx.provider,
            task_id=ctx.task_id,
            source_path=ctx.source,
        )
        ctx.analysis_result = analysis
        return StageResult(success=True, payload=analysis)
