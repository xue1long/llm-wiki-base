"""GeneratorStage — wraps `generate` as a PipelineStage.

Note: the full run_ingest (which also appends a source page and writes
to disk under AtomicContext) lives in src/pipeline/ingest.py and is
called by the dispatcher, not by the stages. This stage is the
"render WikiPage list" step only; the file writes happen in
`run_ingest` after the stages return.
"""
from __future__ import annotations

from ..ports import PipelineContext, StageResult
from .. import generator as _generator_module


class GeneratorStage:
    name = "generator"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        if ctx.analysis_result is None:
            return StageResult(success=False, payload="missing analysis result")
        generate_fn = getattr(_generator_module, "generate")
        pages = await generate_fn(
            paths=ctx.paths,
            analysis=ctx.analysis_result,
            existing_wiki_index="",
            provider=ctx.provider,
            model=ctx.model,
        )
        return StageResult(success=True, payload=pages)
