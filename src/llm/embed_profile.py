"""R11 — embedding capability profile (keyword-only / local / remote).

Audit: the local sentence-transformers fallback was referenced by the
startup code but not declared as a dependency, so a fresh install with a
dead remote provider silently degraded to keyword search while the
service looked healthy. This module is the single place that answers
"what embedding capability does this installation actually have?", so
the readiness probe and operators can see the truth.

Modes:
- ``remote``       — a remote LLM provider is configured (may still fail
                     at runtime, but the capability exists).
- ``local``        — no remote provider, but sentence-transformers is
                     installed (offline local embedding; default 512-dim
                     ``thenlper/gte-small-zh``).
- ``keyword-only`` — neither is available: semantic search is OFF and the
                     system must say so.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def local_embedding_available() -> bool:
    """True when ``sentence_transformers`` is importable (offline fallback)."""
    try:
        __import__("sentence_transformers")
        return True
    except ImportError:
        return False


def embedding_mode() -> str:
    """Return ``remote`` / ``local`` / ``keyword-only`` for this install."""
    try:
        from .registry import ProviderRegistry
        ProviderRegistry.get_default()
        # A default provider is configured → remote capability exists
        # (reachability is a separate concern, handled by readiness).
        return "remote"
    except Exception:
        pass
    if local_embedding_available():
        return "local"
    return "keyword-only"
