"""FastAPI app factory for ruflo-kb HTTP API."""
import asyncio
import logging
import os
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

CLEANUP_INTERVAL_S = 3600  # 1 hour


async def _periodic_cache_cleanup():
    """Background task: run cache cleanup on all registered projects every hour."""
    # Wait for server to fully start before first cleanup.
    await asyncio.sleep(60)

    while True:
        try:
            from ..maintenance.cache_cleanup import cleanup_all
            from ..wiki.core.paths import WikiPaths
            from ..project.registry import GlobalRegistryStore

            reg = GlobalRegistryStore.load()
            for entry in reg.projects.values():
                project_path = Path(entry.path)
                if not project_path.exists():
                    continue
                try:
                    paths = WikiPaths(project_path)
                    results = cleanup_all(paths)
                    total = sum(v for v in results.values() if v > 0)
                    if total > 0:
                        _logger.info(
                            "[cache-cleanup] project=%s cleaned=%s",
                            entry.name, results,
                        )
                except Exception:
                    _logger.debug(
                        "[cache-cleanup] project=%s failed (see trace)", entry.name,
                        exc_info=True,
                    )
        except Exception:
            _logger.debug("[cache-cleanup] background sweep failed", exc_info=True)

        await asyncio.sleep(CLEANUP_INTERVAL_S)


def create_app() -> FastAPI:
    """Build FastAPI app with all routers mounted."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # R12: inject correlation fields (request_id/task_id/project_id)
        # into every log record so the HTTP→Queue→Pipeline→Writer chain is
        # traceable end-to-end.
        import logging
        from ..lib.correlation import CorrelationLogFilter
        logging.getLogger().addFilter(CorrelationLogFilter())

        # Startup: configure the process-global embedding provider + vector
        # store handle for the active project. Audit finding C-1 root cause
        # was that the embedding provider was never wired up at app startup,
        # so any code path that called ``get_embedding_provider()`` returned
        # ``None`` and silently fell back to zero-vector / keyword-only.
        try:
            from ..llm.registry import ProviderRegistry
            from ..llm.provider_factory import (
                create_embedding_provider,
                resolve_embedding_provider_type,
            )
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
            # Falls back to the offline local sentence-transformers provider
            # when no remote provider is usable (no key, deprecated model,
            # unreachable endpoint) so startup never depends on the network.
            provider = None
            try:
                default = ProviderRegistry.get_default()
                candidate = create_embedding_provider(
                    provider=resolve_embedding_provider_type(default.name, default.type),
                    api_key=default.api_key or None,
                    endpoint=default.base_url or None,
                    model=default.default_embedding_model or None,
                )
                # Smoke test: verify the provider actually returns vectors.
                # MiniMax embo-01 is deprecated and returns [] silently.
                test_result = await candidate.embed(["test"])
                if test_result and test_result[0].embedding:
                    provider = candidate
                    set_embedding_provider(provider)
                    _logger.info("[startup] embedding provider: %s", type(candidate).__name__)
                else:
                    _logger.warning("[startup] remote embedding provider returned empty vectors (deprecated model?)")
            except Exception as e:
                _logger.warning(
                    "[startup] remote embedding provider init failed (%s); "
                    "falling back to local sentence-transformers", e
                )

            if provider is None:
                try:
                    from ..llm.local_embed import LocalEmbeddingProvider
                    provider = LocalEmbeddingProvider()
                    set_embedding_provider(provider)
                    _logger.info("[startup] embedding provider: local sentence-transformers")
                except Exception as le:
                    _logger.warning("[startup] local embedding fallback also failed: %s", le)

            # Initialise the vector store for the active project (best-effort).
            # R14: prefer the explicit project root set by `ruflo serve
            # --project-root` (propagated via RUFLO_PROJECT_ROOT so the
            # daemon child inherits it); fall back to CWD only when unset
            # (CLI now requires the flag, so this is a defensive default).
            try:
                from pathlib import Path
                project_root = Path(
                    os.environ.get("RUFLO_PROJECT_ROOT") or Path.cwd()
                )
                paths = ensure_knowledge_base(project_root)
                init_vector_store_for_paths(paths)
                # Wire DecayBridge so heat decay triggers lifecycle transitions
                try:
                    from ..knowledge.core.lifecycle import LifecycleEngine
                    from ..knowledge.lifecycle.decay import DecayBridge
                    from ..wiki.features.heat import set_decay_bridge
                    engine = LifecycleEngine()
                    bridge = DecayBridge(engine)
                    set_decay_bridge(bridge)
                except Exception:
                    pass

                # Initialize KnowledgeKernel for the active project so
                # lifecycle events (knowledge.created / knowledge.updated)
                # are emitted on the global EventBus singleton.
                try:
                    from ..knowledge.kernel import get_kernel
                    get_kernel(project_root)
                except Exception:
                    pass
            except Exception as e:
                _logger.warning("[startup] vector store init failed: %s", e)

            # R7: crash-recovery safety net — mark wiki pages missing from
            # the vector table as pending so a later reconcile (CLI or
            # server-side) re-indexes them. Best-effort; never fails boot.
            try:
                from ..vector.pending import scan_wiki_vector_diff
                from ..vector.store import get_table
                from ..wiki.core.paths import WikiPaths
                _paths = WikiPaths(project_root)
                _table = get_table(_paths)
                if _table is not None:
                    try:
                        _ids = [r["id"] for r in _table.to_pandas().to_dict("records")] \
                            if hasattr(_table, "to_pandas") else []
                        _added = scan_wiki_vector_diff(_paths, _table, _ids)
                        if _added:
                            _logger.info(
                                "[startup] vector-pending scan: %d wiki page(s) "
                                "marked for re-indexing", _added,
                            )
                    except Exception:
                        pass
            except Exception:
                pass

            # R15: warn at startup when the provider registry file is
            # world/group-accessible (it holds plaintext API keys). Advisory
            # only — never fails boot.
            try:
                from ..llm.registry import check_config_permissions
                check_config_permissions()
            except Exception:
                pass

            # Health-check loop (preserved from prior behaviour).
            # Each provider gets a 10-second timeout so a single unreachable
            # provider (e.g. OpenAI behind a TLS-blocking proxy) cannot hang
            # the entire startup sequence.
            try:
                import asyncio
                from ..llm.provider_factory import _create_from_config
                for name, config in ProviderRegistry.load().items():
                    try:
                        provider = _create_from_config(config)
                        health = await asyncio.wait_for(provider.health_check(), timeout=10)
                        if not health.get("ok"):
                            _logger.warning(f"[startup] provider {name!r} unreachable: {health.get('detail')}")
                        # Also check response_format compatibility for OpenAI-compatible providers
                        if health.get("ok"):
                            try:
                                rf = await asyncio.wait_for(provider.check_response_format(), timeout=10)
                                if not rf.get("ok"):
                                    _logger.warning(
                                        f"[startup] provider {name!r} response_format incompatible: "
                                        f"{rf.get('detail')} — ingestion will produce empty stub pages"
                                    )
                            except Exception as rf_exc:
                                _logger.warning(f"[startup] provider {name!r} response_format check error: {rf_exc}")
                        await provider.close()
                    except asyncio.TimeoutError:
                        _logger.warning(f"[startup] provider {name!r} health-check timed out (10s)")
                    except Exception as exc:
                        _logger.warning(f"[startup] provider {name!r} health-check error: {exc}")
            except Exception as e:
                _logger.warning(f"[startup] health check loop error: {e}")
        finally:
            pass

        # Auto-recover pending queue tasks after a server restart.
        # The queue is persisted to disk; PENDING tasks left from a
        # previous run are re-dispatched here (up to 6 concurrent workers).
        # If the queue was paused before the restart (sentinel file exists),
        # skip recovery — the user explicitly asked for a pause.
        try:
            from ..queue.service import get_default_queue_service
            svc = get_default_queue_service()
            status = svc.get_status()
            if status.get("paused"):
                _logger.info(
                    "[startup] queue is paused (%d pending, %d running) — skipping auto-recovery",
                    status["pending_count"], status["running_count"],
                )
            else:
                for _ in range(6):
                    if not svc.advance():
                        break
                status = svc.get_status()
                if status["pending_count"] or status["running_count"]:
                    _logger.info(
                        "[startup] queue recovery: %d pending, %d running",
                        status["pending_count"], status["running_count"],
                    )
        except Exception:
            _logger.warning("[startup] queue recovery failed", exc_info=True)

        # Start background cache cleanup task (runs every hour).
        cleanup_task = asyncio.create_task(_periodic_cache_cleanup())

        yield

        # Cancel background cleanup on shutdown.
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        # Shutdown: close any providers auto-registered during request handling.
        # Without this, every OllamaProvider created via create_llm_provider()
        # would leak its httpx.AsyncClient until the process exits.
        try:
            from ..llm.registry import ProviderRegistry as _PR
            await _PR.aclose_all()
        except Exception as e:
            _logger.warning(f"[shutdown] aclose_all failed: {e}")
        _logger.info("[server] shutting down")

    from .. import __version__ as _app_version
    app = FastAPI(
        title="ruflo-kb API",
        version=_app_version,
        lifespan=lifespan,
    )

    # R1: bearer-token auth for the management surface. When a token is
    # configured (see `ruflo auth-token`), all /api/v1 write ops and
    # provider management require `Authorization: Bearer <token>`;
    # /health stays anonymous. No token → loopback-only mode, no auth.
    from .auth_middleware import add_auth_middleware
    add_auth_middleware(app)

    # R12: per-request correlation id (injected into logs via the filter).
    import uuid
    from ..lib.correlation import set_correlation, clear_correlation

    @app.middleware("http")
    async def _correlation_middleware(request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        set_correlation(request_id=request_id)
        try:
            return await call_next(request)
        finally:
            clear_correlation()

    from .routes import health, projects, files, search, ingest, reviews, chat, schema, agent_cli, analysis, providers, tags, quality, heat, templates, scenario_templates, capture
    for router in [health.router, projects.router, files.router, search.router,
                   ingest.router, reviews.router, chat.router, schema.router, agent_cli.router,
                   analysis.router, providers.router, tags.router, quality.router, heat.router, templates.router, scenario_templates.router, capture.router]:
        app.include_router(router)

    # R5: readiness probe (per-component, 200/503) — /health stays liveness.
    from .ready import router as ready_router
    app.include_router(ready_router)

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
