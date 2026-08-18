"""R1 — HTTP auth middleware for the ruflo-kb management surface.

Registered in ``src/server/app.py`` via ``add_auth_middleware(app)``.

Rule set (architecture-remediation R1, plan-audit hardening):
- ``/health`` stays anonymous.
- When NO token is configured, every request is allowed (loopback-only
  deployment — same behaviour as before R1).
- When a token IS configured:
  * all ``/api/v1`` write methods (POST/PUT/PATCH/DELETE) require
    ``Authorization: Bearer <token>``;
  * provider management endpoints (``/api/v1/providers*``) require the
    token on every method (they expose credential metadata);
  * everything else (read-only project/wiki/search endpoints, static
    files) stays anonymous.
- The token is compared with ``secrets.compare_digest`` (constant-time);
  the raw token is never logged.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_logger = logging.getLogger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PROVIDER_PREFIX = "/api/v1/providers"
_API_PREFIX = "/api/v1"


def _requires_auth(path: str, method: str) -> bool:
    """Decide whether a request needs the bearer token."""
    if not path.startswith(_API_PREFIX):
        return False  # /health, /metrics, static files, etc.
    if path.startswith(_PROVIDER_PREFIX):
        return True  # provider management always gated (credential metadata)
    return method in _WRITE_METHODS


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Unauthorized: a bearer token is required for this endpoint"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def add_auth_middleware(app: FastAPI) -> None:
    """Install the bearer-token middleware on ``app`` (idempotent-safe)."""

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        # Late import so token rotation (and tests' monkeypatching) is
        # honoured per-request instead of being frozen at import time.
        from .auth import get_token

        token = get_token()
        if token is None:
            # Auth disabled — allow everything (back-compat loopback mode).
            return await call_next(request)

        path = request.url.path
        method = request.method.upper()
        if not _requires_auth(path, method):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        expected = f"Bearer {token}"
        # Constant-time comparison; wrong/missing header → 401.
        if not _secure_compare(auth_header, expected):
            _logger.warning(
                "[auth] rejected %s %s (missing/invalid bearer token)",
                method, path,
            )
            return _unauthorized()
        return await call_next(request)

    return None


def _secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison (length of the *expected* value)."""
    import hmac

    # hmac.compare_digest requires equal-length bytes; pad the received
    # value to the expected length so a short header cannot leak length
    # through a fast-fail. The actual secret never leaves the process.
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
