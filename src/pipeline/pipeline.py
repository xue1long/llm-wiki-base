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
    # Audit I5: forward the originating project_id so _on_collector_done
    # resolves the correct project's WikiPaths.
    done_payload_dict = {
        "task_id": done_payload.task_id,
        "raw_path": done_payload.raw_path,
        "content": done_payload.content,
        "source": getattr(done_payload, "source", None),
    }
    if "project_id" in payload:
        done_payload_dict["project_id"] = payload["project_id"]
    await _on_collector_done(done_payload_dict)


async def _on_collector_done(payload):
    """Run the analyzer + generator + atomic write + index + log.

    Audit I5: when the originating ``project_id`` is present in the
    payload, resolve the project's WikiPaths so multi-project ingest
    writes to the correct project (not the CWD-relative default).
    """
    task_id = payload["task_id"] if isinstance(payload, dict) else payload.task_id
    raw_path_str = payload["raw_path"] if isinstance(payload, dict) else payload.raw_path
    content = payload["content"] if isinstance(payload, dict) else payload.content
    project_id = payload.get("project_id") if isinstance(payload, dict) else None

    original_source = payload.get("source") if isinstance(payload, dict) else getattr(payload, "source", None)

    try:
        paths = _resolve_wiki_paths(project_id=project_id)
        await run_ingest(
            paths=paths,
            source_path=Path(raw_path_str),
            source_text=content,
            provider=_get_provider(),
            task_id=task_id,
        )
        # Post-success: NOW move the original source into Processing so the
        # next queue retry cannot re-read it. Pre-fix this happened in
        # collector.collect() BEFORE the LLM ran, which meant any LLM
        # failure caused all 3 retries to hit FileNotFoundError. See
        # tests/test_pipeline/test_collector_retry_path.py.
        if original_source:
            try:
                from ..inbox.manager import get_inbox_manager
                from ..permissions import AgentType, Permission, enforce_permission
                enforce_permission(AgentType.COLLECTOR, original_source, Permission.WRITE)
                inbox = get_inbox_manager()
                src_path = Path(original_source)
                if src_path.exists():
                    inbox.move_to_processing(original_source)
            except FileNotFoundError:
                # Already moved by a prior successful run — nothing to do.
                pass
            except Exception as mv_exc:
                _logger.warning(
                    "[pipeline] post-success move failed for %s: %s", task_id, mv_exc,
                )
        update_task_status(task_id, TaskStatus.APPROVED)
    except Exception as exc:
        _logger.exception("ingest failed for %s", task_id)
        update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
    finally:
        release_in_flight(task_id)


def _get_provider():
    """Resolve the configured default LLM provider (audit I4).

    Previously hard-coded ``"openai"`` — ignored ``RUFLO_LLM_PROVIDER``
    and the registry's named-default. Now reads ``ProviderRegistry.get_default()``
    so the configured provider is honoured by the pipeline. Falls back to
    OpenAI only when the registry is empty / corrupt (so import-time tests
    still work).
    """
    from ..llm.provider_factory import create_llm_provider
    from ..llm.registry import ProviderRegistry, RegistryCorruptError, ProviderNotFoundError
    try:
        cfg = ProviderRegistry.get_default()
        return create_llm_provider(cfg.name)
    except (RegistryCorruptError, ProviderNotFoundError, ValueError):
        # No default available (e.g. tests with empty registry): fall back
        # to OpenAI so the pipeline still functions.
        return create_llm_provider("openai")


def _resolve_wiki_paths(project_id: str | None = None):
    """Resolve WikiPaths for the active project (audit I5).

    When ``project_id`` is provided, look up the project's path in the
    global registry and build WikiPaths from it. Falls back to CWD for
    callers that do not yet thread project_id through (e.g. tests / CLI
    single-project mode). CWD is treated as the project root, so the
    wiki tree is the canonical ``<root>/wiki/`` shape.
    """
    from ..wiki.core.paths import WikiPaths
    if project_id is not None:
        try:
            from ..project.registry import GlobalRegistryStore
            entry = GlobalRegistryStore.by_id(project_id)
            if entry is not None:
                return WikiPaths(Path(entry.path))
        except Exception:
            pass
    # WikiPaths interprets root as the project root, so the wiki tree
    # lives at <root>/wiki/ — matches the canonical wiki-v2 shape.
    return WikiPaths(Path.cwd())


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
