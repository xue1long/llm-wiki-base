# ruflo-kb/src/pipeline/pipeline.py
import asyncio
import logging

from ..events.event_bus import event_bus
from ..events.events import EventName
from ..queue.queue import update_task_status
from ..types import TaskStatus
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes
from ..wiki.indexer import append_to_index
from ..wiki.logger import log_event
from ..wiki.page_writer import write_page
from ..wiki.paths import WikiPaths
from ..wiki.types import WikiPage
from .analyzer import analyze
from .generator import generate
from .collector import collect
from .processor import process
from .librarian import archive

_logger = logging.getLogger(__name__)

event_bus.on("collector:start", lambda p: _on_collector_start(p))
event_bus.on(EventName.COLLECTOR_DONE, lambda p: _on_collector_done(p))
event_bus.on(EventName.PROCESSOR_DONE, lambda p: _on_processor_done(p))

def _on_collector_start(payload: dict):
    task_id = payload["task_id"]
    update_task_status(task_id, TaskStatus.RUNNING)
    asyncio.create_task(collect(task_id, payload["source"], payload["source_type"]))

async def _on_collector_done(payload):
    task_id = payload.task_id
    await process(task_id, payload.raw_path, payload.content)

async def _on_processor_done(payload):
    task_id = payload.task_id
    await archive(task_id, payload.note_path)


async def run_ingest(
    paths: WikiPaths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
) -> list[WikiPage]:
    """Run full 2-step pipeline + write pages + update index + log.

    Returns list of generated WikiPage objects.
    """
    # Step 1: Analyze
    analysis = await analyze(
        source_text=source_text,
        source_ext=source_path.suffix if hasattr(source_path, "suffix") else ".pdf",
        existing_wiki_index="",
        folder_context=folder_context,
        provider=provider,
        task_id=task_id,
        source_path=str(source_path),
    )

    # Step 2: Generate
    pages = await generate(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
    )

    # Atomic write all pages + index update + log
    with AtomicContext(flush_callback=flush_pending_writes):
        for page in pages:
            write_page(paths, page)
        append_to_index(
            paths,
            [(p.id, p.type, p.title) for p in pages],
        )
        log_event(
            paths,
            event="ingest",
            task_id=task_id,
            detail=f"generated {len(pages)} pages from {source_path.name}",
        )

    return pages
