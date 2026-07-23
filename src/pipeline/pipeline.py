# ruflo-kb/src/pipeline/pipeline.py
import asyncio
import logging
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName
from ..queue.queue import release_in_flight, update_task_status
from ..types import TaskStatus
from ..lib.atomic_ctx import AtomicContext
from ..lib.write_hooks import flush_pending_writes
from ..wiki.features.indexer import append_to_index
from ..wiki.features.logger import log_event
from ..wiki.storage.page_writer import write_page
from ..wiki.core.paths import WikiPaths
from ..wiki.core.types import WikiPage
from .analyzer import analyze
from .generator import generate
from .collector import collect

_logger = logging.getLogger(__name__)

event_bus.on("collector:start", lambda p: _on_collector_start(p))
event_bus.on(EventName.COLLECTOR_DONE, lambda p: _on_collector_done(p))

def _schedule_collector(task_id: str, source: str, source_type) -> None:
    """Run the collector and release in-flight state if it fails pre-done."""
    async def runner():
        try:
            await collect(task_id, source, source_type)
        except Exception as exc:
            _logger.exception("collector failed for %s", task_id)
            try:
                update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
            finally:
                release_in_flight(task_id)

    asyncio.create_task(runner())


def _on_collector_start(payload: dict):
    task_id = payload["task_id"]
    update_task_status(task_id, TaskStatus.RUNNING)
    _schedule_collector(task_id, payload["source"], payload["source_type"])

async def _on_collector_done(payload):
    task_id = payload.task_id
    try:
        paths = _resolve_wiki_paths()
        await run_ingest(
            paths=paths,
            source_path=Path(payload.raw_path),
            source_text=payload.content,
            provider=_get_provider(),
            task_id=task_id,
        )
        update_task_status(task_id, TaskStatus.APPROVED)
    except Exception as exc:
        _logger.exception("ingest failed for %s", task_id)
        update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
    finally:
        release_in_flight(task_id)


def _get_provider():
    from ..llm.provider_factory import create_llm_provider
    return create_llm_provider("openai")


def _resolve_wiki_paths():
    from ..wiki.core.paths import WikiPaths
    root = Path.cwd() / "Knowledge"
    return WikiPaths(root)


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
