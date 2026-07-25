"""AnalyzerStage — wraps `analyze` as a PipelineStage."""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import analyzer as _analyzer_module


class AnalyzerStage:
    name = "analyzer"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if ctx.collector_result is None:
            return StageResult(success=False, payload="missing collector result")
        analyze_fn = getattr(_analyzer_module, "analyze")
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
