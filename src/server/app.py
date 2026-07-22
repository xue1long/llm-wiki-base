"""FastAPI app factory for ruflo-kb HTTP API."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI


_logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build FastAPI app with all routers mounted."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: ping providers
        from ..llm.registry import ProviderRegistry
        from ..llm.provider_factory import _create_from_config
        try:
            for name, config in ProviderRegistry.load().items():
                provider = _create_from_config(config)
                health = await provider.health_check()
                if not health.get("reachable"):
                    _logger.warning(f"[startup] provider {name!r} unreachable: {health.get('error')}")
                await provider.close()
        except Exception as e:
            _logger.warning(f"[startup] health check failed: {e}")
        yield
        # Shutdown: cleanup
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