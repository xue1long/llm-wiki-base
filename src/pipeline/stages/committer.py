"""CommitStage — writes WikiPage(s) to disk and updates index/log."""
from __future__ import annotations

import time

from ...wiki.core.paths import WikiPaths
from ...wiki.core.types import WikiPage
from ...wiki.features.indexer import append_to_index
from ...wiki.features.logger import log_event
from ...wiki.storage.ensure import ensure_knowledge_base
from ...wiki.storage.page_writer import write_page
from ..ports import PipelineContext, StageResult


class CommitStage:
    """Writes WikiPage(s) to disk, updates index.md and log.md.

    This is the final stage in the candidate pipeline. It takes the
    `pages` from GeneratorStage and persists them atomically.
    """

    name = "committer"

    async def run(self, ctx: PipelineContext, prev_result) -> StageResult:
        """Stage protocol: extract pages and write to disk."""
        if prev_result is None:
            return StageResult(success=False, payload={"error": "no prev_result"})

        payload = prev_result.payload
        if not isinstance(payload, dict) or "pages" not in payload:
            return StageResult(success=False, payload={"error": "no pages in payload"})

        pages: list[WikiPage] = payload["pages"]
        paths: WikiPaths = ctx.paths

        ensure_knowledge_base(paths.root)

        written_ids: list[str] = []
        errors: list[dict] = []

        for page in pages:
            try:
                write_page(paths, page)
                append_to_index(paths, [(page.id, page.type, page.title)])
                written_ids.append(page.id)
            except Exception as e:
                errors.append({"page_id": page.id, "error": str(e)})

        if written_ids:
            log_event(
                paths=paths,
                event="ingest_commit",
                task_id=ctx.task_id,
                detail=f"committed {len(written_ids)} pages",
                extra={"pages": written_ids},
            )

        return StageResult(
            success=len(written_ids) > 0,
            payload={"written_ids": written_ids, "errors": errors}
        )
