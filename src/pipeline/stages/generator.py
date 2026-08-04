"""GeneratorStage — wraps `generate_from_knowledge_object` as a PipelineStage.

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
        """Stage protocol: extract KnowledgeObject and generate WikiPages."""
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})

        payload = prev_result.payload
        if not isinstance(payload, dict) or "knowledge_object" not in payload:
            return StageResult(success=False, payload={"error": "no knowledge_object in payload"})

        ko = payload["knowledge_object"]
        candidate = payload.get("candidate")

        pages = await _generator_module.generate_from_knowledge_object(
            ko=ko,
            candidate=candidate,
            paths=ctx.paths,
            existing_wiki_index="",
            provider=ctx.provider,
            source_slug_map={},
            source_text=ctx.source,
        )

        return StageResult(success=True, payload={"pages": pages, "knowledge_object": ko})
