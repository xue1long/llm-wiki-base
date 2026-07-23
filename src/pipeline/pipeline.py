# ruflo-kb/src/pipeline/pipeline.py
import asyncio
import logging
from pathlib import Path

from ..events.event_bus import event_bus
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


def _dispatch_collector_start(payload) -> None:
    """Synchronous adapter for the collector:start event.

    Runs the full collector -> ingest chain on a single event loop. In the
    no-running-loop case (`enqueue_task(...)` called from a sync thread, the
    production entry path), we drive the loop with `asyncio.run` and the
    chain itself `await`s both `collect()` and `_on_collector_done(payload)`
    on the same coroutine, so when `asyncio.run` returns the loop has no
    outstanding tasks and the child ingestion cannot be cancelled.

    The previous design used `loop.create_task` to schedule the done handler
    from inside a running coroutine. Under `asyncio.run`, the temporary loop
    is closed as soon as the outer coroutine returns, which cancelled the
    child task before `run_ingest` could finish.
    """
    coro = _on_collector_start(payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop — safe to use asyncio.run since `_on_collector_start` now
        # drives both the collector and the ingest on the same coroutine
        # via direct awaits, with no fire-and-forget child tasks.
        try:
            asyncio.run(coro)
        except Exception:
            _logger.exception("collector chain dispatch failed")
        return
    # Persistent loop case (e.g. tests already inside asyncio.run): schedule
    # the whole chain as a single task. Callers wanting completion should
    # `await` it themselves; no internal handoff via the event bus.
    loop.create_task(coro)


# NB: there is no COLLECTOR_DONE handler registration. _on_collector_done is
# driven directly from _on_collector_start once collect() returns its payload,
# which keeps the chain on one coroutine and avoids the asyncio.run
# cancellation race documented in the audit. `collect()` still emits
# EventName.COLLECTOR_DONE for any external listeners.
event_bus.on("collector:start", _dispatch_collector_start)


async def _on_collector_start(payload: dict):
    """Run the collector, then directly drive the ingest stage.

    Returns nothing. Always either (a) marks the task APPROVED/FAILED with
    `_in_flight` released, or (b) marks it FAILED before collector completion
    and releases `_in_flight`. Never leaves the task RUNNING.
    """
    task_id = payload["task_id"]
    update_task_status(task_id, TaskStatus.RUNNING)
    try:
        done_payload = await collect(task_id, payload["source"], payload["source_type"])
    except Exception as exc:
        _logger.exception("collector failed for %s", task_id)
        try:
            update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
        finally:
            release_in_flight(task_id)
        return
    # Internal handoff: drive the ingest stage on the same coroutine so the
    # temporary asyncio.run loop cannot close before run_ingest completes.
    # External listeners of `collector:done` still receive the emit from
    # `collect()`, but the pipeline does not rely on the bus dispatch here.
    await _on_collector_done(done_payload)


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
