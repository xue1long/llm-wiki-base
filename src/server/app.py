"""FastAPI app factory for ruflo-kb HTTP API."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI


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
            from ..wiki.ensure import ensure_knowledge_base

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

    from .routes import health, projects, files, search, ingest, reviews, chat, schema
    for router in [health.router, projects.router, files.router, search.router,
                   ingest.router, reviews.router, chat.router, schema.router]:
        app.include_router(router)

    return app
