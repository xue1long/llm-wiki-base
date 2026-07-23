"""Regression test for audit finding C-7 (server enqueued but never processed).

`src.pipeline.pipeline` registers the ``collector:start`` handler on the
singleton ``event_bus`` at module import time. The HTTP server only processes
queued ingest tasks if that handler is registered, so ``src.server.app`` MUST
import the pipeline module as a side effect.
"""
import sys


def test_server_app_imports_pipeline():
    """Importing src.server.app must transitively import src.pipeline.pipeline.

    Otherwise POST /api/v1/projects/{id}/ingest enqueues tasks onto
    .kb-queue.json that are never processed — the event is emitted to
    a bus with no listeners.
    """
    # Drop both modules so the re-import has clean side effects regardless
    # of test ordering (other tests in this session may have imported
    # either module first).
    for mod in ("src.pipeline.pipeline", "src.server.app"):
        sys.modules.pop(mod, None)

    import src.server.app  # noqa: F401

    assert "src.pipeline.pipeline" in sys.modules, (
        "src/server/app.py does not import src.pipeline.pipeline. "
        "Queued ingest tasks will never be processed — the collector:start "
        "event has no listener. Add `import src.pipeline.pipeline` to "
        "src/server/app.py (e.g. inside create_app() or at module top)."
    )


def test_create_app_registers_collector_start_handler():
    """After create_app(), the event_bus has at least one collector:start
    handler from the pipeline module. This catches regressions where the
    server stops importing pipeline (e.g. someone removes the import
    thinking it's unused)."""
    from src.events.event_bus import event_bus
    from src.server.app import create_app

    create_app()

    handlers = event_bus._handlers.get("collector:start", set())
    assert handlers, (
        "create_app() did not register any collector:start handler. "
        "The pipeline module must be imported as a side effect of the "
        "server module."
    )
    # The handler from src/pipeline/pipeline.py is named
    # ``_dispatch_collector_start`` and lives in the ``src.pipeline.pipeline``
    # module.
    module_names = {h.__module__ for h in handlers}
    assert any("pipeline" in m for m in module_names), (
        f"Expected collector:start handler from src.pipeline.* module; "
        f"got modules {module_names}"
    )