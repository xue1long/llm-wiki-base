"""GET /metrics endpoint — Prometheus text format (FastAPI router).

The router is created lazily so importing this module does NOT require FastAPI
unless the consumer actually invokes the endpoint registration. Persistence
runs synchronously on every request and prunes rows older than 24 hours.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter

# Module-level router reference; populated by `get_router()` on first use.
_router = None


def get_router():
    """Return the FastAPI router for /metrics. Imports FastAPI on first call."""
    global _router
    if _router is not None:
        return _router
    from fastapi import APIRouter
    from fastapi.responses import PlainTextResponse

    from ..metrics import MetricsRegistry
    from ..metrics.persistence import persist_counter, persist_gauge, cleanup_old
    from ..metrics.prometheus_format import to_prometheus_text

    # Default DB location; overridden by app factory in http-api-mcp plan.
    try:
        from ..project.paths import config_dir
        _db_dir = config_dir()
    except Exception:
        from pathlib import Path
        _db_dir = Path.home() / ".config" / "ruflo-kb"

    _default_db_path = _db_dir / "metrics.db"

    router = APIRouter()

    @router.get("/metrics")
    async def metrics_endpoint():
        metrics = MetricsRegistry.all_metrics()
        db_path = _default_db_path
        for m in metrics:
            if hasattr(m, "_values") and not hasattr(m, "_counts"):
                for key, val in m._values.items():
                    labels = dict(zip(m.label_names, key))
                    if m.__class__.__name__ == "Counter":
                        persist_counter(db_path, m.name, labels, val)
                    else:
                        persist_gauge(db_path, m.name, labels, val)
        cleanup_old(db_path)
        text = to_prometheus_text(metrics)
        return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")

    _router = router
    return router


# Public name used by the http-api-mcp plan's app factory.
router = None
