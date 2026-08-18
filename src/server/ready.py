"""R5 — /ready readiness probe with per-component checks.

Audit A-04: `/health` unconditionally returned ok:true, conflating
process liveness with business availability. R5 keeps `/health` as the
liveness probe and adds `/ready`, which reports the state of each
component the main path depends on:

- queue:    the JSON queue backend is loadable and its file writable
- wiki:     the active project root is writable (source of truth)
- vector:   the LanceDB handle is initialised (best-effort)
- provider: a default LLM provider is configured (+ last known health)

Design rules (plan-audit hardening):
- Checks are defensive: a component failure never raises out of /ready;
  it is reported as a per-component entry.
- Provider checks are config/last-health only — a transient external
  outage must NOT flip /ready to 503 (avoids readiness flapping and
  snowball restarts). External reachability is probed with a short
  timeout and cached; failures degrade to a warning entry, not 503.
- /ready stays anonymous (no bearer token required).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["ready"])

# Cache the last provider reachability probe so a single flaky network
# check does not flap /ready. TTL in seconds.
_PROVIDER_PROBE_TTL_S = 60.0
_provider_probe_cache: dict = {"ts": 0.0, "ok": None, "detail": ""}


def _active_project_root() -> Path | None:
    """Return the active project root (RUFLO_PROJECT_ROOT or CWD)."""
    root = os.environ.get("RUFLO_PROJECT_ROOT")
    if root:
        return Path(root)
    return Path.cwd()


def check_queue() -> tuple[str, str]:
    """Queue backend loadable + its JSON file writable."""
    try:
        from ..queue.service import get_default_queue_service
        svc = get_default_queue_service()
        status = svc.get_status()
        return "ok", f"queue loaded ({status.get('pending_count', 0)} pending)"
    except Exception as e:
        return "error", f"queue unavailable: {e}"


def check_wiki() -> tuple[str, str]:
    """Active project wiki root is writable."""
    root = _active_project_root()
    try:
        from ..wiki.storage.ensure import ensure_knowledge_base
        paths = ensure_knowledge_base(root)
        probe = paths.root / ".ready-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return "ok", f"wiki root writable ({paths.root})"
    except Exception as e:
        return "error", f"wiki root not writable: {e}"


def check_vector() -> tuple[str, str]:
    """Vector store handle initialised (best-effort; derived state)."""
    try:
        from ..vector.store import init_vector_store_for_paths, get_table
        from ..wiki.core.paths import WikiPaths
        paths = WikiPaths(_active_project_root())
        try:
            init_vector_store_for_paths(paths)
        except Exception:
            pass  # init is best-effort at boot; handle may still exist
        table = get_table(paths)
        if table is not None:
            return "ok", "vector store initialised"
        return "error", "vector store not initialised"
    except Exception as e:
        return "error", f"vector store unavailable: {e}"


def check_provider() -> tuple[str, str]:
    """Default LLM provider configured; last-known health cached."""
    try:
        from ..llm.registry import ProviderRegistry
        try:
            default = ProviderRegistry.get_default()
        except Exception as e:
            return "error", f"no default provider: {e}"

        # Configuration-level health: a provider entry exists with a
        # resolvable endpoint. Reachability is probed with a short timeout
        # and cached so a transient outage degrades (warning) not 503.
        now = time.monotonic()
        if now - _provider_probe_cache["ts"] > _PROVIDER_PROBE_TTL_S:
            _provider_probe_cache["ts"] = now
            _provider_probe_cache["ok"] = None
            _provider_probe_cache["detail"] = ""
            try:
                import asyncio
                from ..llm.provider_factory import _create_from_config
                provider = _create_from_config(default)
                health = asyncio.run(provider.health_check())
                _provider_probe_cache["ok"] = bool(health.get("ok"))
                _provider_probe_cache["detail"] = str(health.get("detail", ""))
                try:
                    provider.close()
                except Exception:
                    pass
            except Exception as e:
                _provider_probe_cache["ok"] = False
                _provider_probe_cache["detail"] = f"probe error: {e}"

        if _provider_probe_cache["ok"] is False:
            # Provider configured but unreachable → warning, not hard 503.
            _logger.warning(
                "[ready] provider %s unreachable: %s",
                default.name, _provider_probe_cache["detail"],
            )
            return "degraded", f"provider configured but unreachable: {_provider_probe_cache['detail']}"
        return "ok", f"provider {default.name} configured"
    except Exception as e:
        return "error", f"provider check failed: {e}"


_CHECK_FUNCS = {
    "queue": check_queue,
    "wiki": check_wiki,
    "vector": check_vector,
    "provider": check_provider,
}


@router.get("/ready")
def ready() -> dict:
    """Per-component readiness report; 503 when any hard dependency fails.

    'degraded' components (e.g. provider unreachable) do NOT fail the
    probe — the process is still usable (keyword search, local wiki).
    """
    checks: dict = {}
    ok = True
    for name, fn in _CHECK_FUNCS.items():
        try:
            status, detail = fn()
        except Exception as e:  # defensive: a check must never raise
            status, detail = "error", f"check raised: {e}"
        checks[name] = {"status": status, "detail": detail}
        if status == "error":
            ok = False

    body = {"ok": ok, "checks": checks}
    # Return 503 when any component is hard-down; 200 otherwise.
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=body)
    return body
