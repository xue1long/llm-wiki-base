"""FastAPI app factory for ruflo-kb HTTP API."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# Importing the pipeline package triggers ``src.pipeline.__init__``,
# which (a) registers the ``collector:start`` handler on the singleton
# ``event_bus`` via ``_register_event_handlers_if_needed`` and (b)
# installs the compat shim at ``sys.modules['src.pipeline.pipeline']``
# for legacy imports / monkey-patching. Without this, the HTTP server
# enqueues ingest tasks via POST /api/v1/projects/{id}/ingest but no
# listener ever picks them up — audit finding C-7. Regression covered
# by tests/test_server/test_app_registers_pipeline.py.
import src.pipeline  # noqa: F401  (registers event_bus handler + shim)


_logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build FastAPI app with all routers mounted."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: configure the process-global embedding provider + vector
        # store handle for the active project. Audit finding C-1 root cause
        # was that the embedding provider was never wired up at app startup,
        # so any code path that called ``get_embedding_provider()`` returned
        # ``None`` and silently fell back to zero-vector / keyword-only.
        try:
            from ..llm.registry import ProviderRegistry
            from ..llm.provider_factory import create_embedding_provider
            from ..llm.embedding_runtime import set_embedding_provider
            from ..vector.store import init_vector_store_for_paths
            from ..wiki.storage.ensure import ensure_knowledge_base
            from .ingest_tracker import init_tracker  # FRONTEND_DESIGN §14.1

            # Subscribe to ingest task lifecycle events so the web frontend
            # can poll status. Must run before any ingest happens.
            init_tracker()

            # Auto-discover and register KB projects found in DEFAULT_SEARCH_PATHS
            # (including knowledge/ under CWD). Skips already-registered projects.
            # Runs on every startup so newly cloned repos are picked up immediately.
            from ..project.discovery import auto_register_on_first_run
            discovered = auto_register_on_first_run()
            if discovered:
                _logger.info("[startup] discovered %d new project(s): %s",
                              len(discovered), [c.name for c in discovered])

            # Initialise embedding provider from the default registry entry.
            try:
                default = ProviderRegistry.get_default()
                provider = create_embedding_provider(
                    provider=default.type,
                    api_key=default.api_key or None,
                    endpoint=default.base_url or None,
                    model=default.default_embedding_model or None,
                )
                set_embedding_provider(provider)
            except Exception as e:
                _logger.warning("[startup] embedding provider init failed: %s", e)

            # Initialise the vector store for the active project (best-effort;
            # resolved from CWD; adjust if the API gains a project selector).
            try:
                from pathlib import Path
                project_root = Path.cwd()
                paths = ensure_knowledge_base(project_root)
                init_vector_store_for_paths(paths)
            except Exception as e:
                _logger.warning("[startup] vector store init failed: %s", e)

            # Health-check loop (preserved from prior behaviour).
            try:
                from ..llm.provider_factory import _create_from_config
                for name, config in ProviderRegistry.load().items():
                    provider = _create_from_config(config)
                    health = await provider.health_check()
                    if not health.get("ok"):
                        _logger.warning(f"[startup] provider {name!r} unreachable: {health.get('detail')}")
                    await provider.close()
            except Exception as e:
                _logger.warning(f"[startup] health check failed: {e}")
        finally:
            pass

        yield

        # Shutdown: close any providers auto-registered during request handling.
        # Without this, every OllamaProvider created via create_llm_provider()
        # would leak its httpx.AsyncClient until the process exits.
        try:
            from ..llm.registry import ProviderRegistry as _PR
            await _PR.aclose_all()
        except Exception as e:
            _logger.warning(f"[shutdown] aclose_all failed: {e}")
        _logger.info("[server] shutting down")

    app = FastAPI(
        title="ruflo-kb API",
        version="0.2.0",
        lifespan=lifespan,
    )

    from .routes import health, projects, files, search, ingest, reviews, chat, schema, agent_cli, analysis, providers
    for router in [health.router, projects.router, files.router, search.router,
                   ingest.router, reviews.router, chat.router, schema.router, agent_cli.router,
                   analysis.router, providers.router]:
        app.include_router(router)

    # Mount /metrics endpoint (Plan 7 fix; previously dead code).
    # get_router() is idempotent — caches the router at module level so
    # the DB path is locked to the first call's project. Multi-project
    # server deployments would need per-project routers (out of scope here).
    from .metrics_route import get_router as _get_metrics_router
    app.include_router(_get_metrics_router())

    # Mount web UI static files
    web_dir = Path(__file__).parent.parent.parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
