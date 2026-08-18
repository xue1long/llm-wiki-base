"""R1 — bearer-token auth for the HTTP management surface.

Design (architecture-remediation R1, plan-audit hardening):

- A single bearer token protects all ``/api/v1`` write operations and
  provider management endpoints. ``/health`` stays anonymous.
- Token lifecycle lives in the existing user config dir (``config_dir()``)
  as ``auth.json``; it is generated/rotated via the CLI, never logged,
  and rotation invalidates the old token immediately.
- No token configured → the API behaves exactly as before (loopback-only
  default deployment). Non-loopback binds are refused at the CLI layer
  unless a token exists (see ``src/cli_ext/serve.py``).

The middleware itself is registered in ``src/server/app.py``; this module
holds the token store, generation, and loopback helpers so both the CLI
and the middleware share one implementation.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

from ..lib.write_hooks import safe_write
from ..project.paths import config_dir

_logger = logging.getLogger(__name__)

AUTH_FILE_NAME = "auth.json"

# Hosts that never require a token (loopback only). Anything else is
# "non-loopback" and therefore gated by ``require_token_for_host``.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def auth_path() -> Path:
    """Path to the bearer-token file (``<config_dir>/auth.json``)."""
    return config_dir() / AUTH_FILE_NAME


def get_token() -> str | None:
    """Return the configured bearer token, or None when auth is disabled.

    Reads the file on every call so token rotation takes effect for the
    *next* request without a server restart. A missing, corrupt, or empty
    file is treated as "no token" (loopback-only mode).
    """
    path = auth_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _logger.warning("[auth] cannot read %s (%s); treating as no token", path, e)
        return None
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        return None
    return token


def set_token(token: str) -> None:
    """Persist the bearer token atomically (``auth.json``, chmod 0600).

    Rotation is a plain overwrite: callers generate a new token and call
    this — the old value is gone the moment the file is replaced, so the
    old token stops working immediately.
    """
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_write(path, json.dumps({"token": token}, indent=2))
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError, AttributeError):
        pass  # Windows chmod is best-effort; strongest POSIX guarantee kept


def clear_token() -> None:
    """Remove the token file entirely, disabling auth (loopback-only mode)."""
    path = auth_path()
    if path.exists():
        try:
            path.unlink()
        except OSError as e:
            _logger.warning("[auth] failed to remove %s: %s", path, e)


def generate_token() -> str:
    """Generate a new cryptographically-random bearer token."""
    return secrets.token_urlsafe(48)


def is_loopback_host(host: str) -> bool:
    """True when ``host`` is a loopback address (or empty).

    Accepts ``127.0.0.1``/``localhost``/``::1`` and the whole
    ``127.0.0.0/8`` range. IPv6 link-local/ULA and any other address are
    non-loopback.
    """
    host = (host or "").strip().lower()
    if not host:
        return True
    if host in _LOOPBACK_HOSTS:
        return True
    if host.startswith("127."):
        # 127.x.y.z — the whole loopback /8 is local.
        parts = host.split(".")
        return len(parts) == 4 and all(p.isdigit() for p in parts)
    return False


def require_token_for_host(host: str) -> bool:
    """True when a non-loopback bind must have a token configured.

    Loopback binds never require a token (back-compat with the current
    default deployment). Any other host is a management-surface exposure
    and therefore requires the operator to have configured auth.
    """
    return not is_loopback_host(host)


__all__ = [
    "auth_path",
    "get_token",
    "set_token",
    "clear_token",
    "generate_token",
    "is_loopback_host",
    "require_token_for_host",
]
