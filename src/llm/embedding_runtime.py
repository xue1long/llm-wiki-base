"""Process-global embedding provider singleton shared by librarian + searcher.

Background
----------
Before this module existed, ``src.pipeline.librarian`` and
``src.searcher.hybrid_search`` each kept their own module-level
``_embedding_provider`` global. Two side effects:

* Calls to ``set_embedding_provider()`` only configured whichever module
  happened to be imported first.
* The 1536-dim / 768-dim mismatch (audit finding I-vector-9) was hidden by
  the fact that callers fell through to zero-vector fallbacks.

This module is the single source of truth. Both ``librarian`` and
``hybrid_search`` read from ``get_embedding_provider()``; initialisation
happens in the FastAPI lifespan hook (``src.server.app``).

Public API
----------
* :func:`set_embedding_provider(provider)` — install the singleton.
* :func:`get_embedding_provider()` — fetch it; raises :class:`RuntimeError`
  when nothing is configured.
* :func:`__reset_for_testing()` — clear the singleton (test-only).
"""
from threading import Lock
from typing import Optional, Protocol


class EmbeddingProvider(Protocol):
    """Narrow protocol — any object exposing ``embed(texts) -> list[list[float]]``.

    Concrete provider classes (e.g. :class:`src.llm.openai_provider.OpenAIEmbeddingProvider`)
    return ``list[EmbeddingResponse]`` from their ``embed`` method. The runtime
    here keeps the protocol intentionally narrow so test doubles and concrete
    providers are both acceptable as long as callers can consume the structure.
    Callers that need richer objects should use the concrete class APIs.
    """

    def embed(self, texts: list[str]) -> list[list[float]]: ...


_impl: Optional["EmbeddingProvider"] = None
_lock = Lock()


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Install the process-global embedding provider.

    Replaces any prior instance. Thread-safe.
    """
    global _impl
    with _lock:
        _impl = provider


def get_embedding_provider() -> EmbeddingProvider:
    """Fetch the configured embedding provider.

    Raises:
        RuntimeError: when no provider has been installed. Callers should
            configure one during project / app startup.
    """
    if _impl is None:
        raise RuntimeError(
            "Embedding provider not configured. Call set_embedding_provider() "
            "during project / app startup."
        )
    return _impl


def __reset_for_testing() -> None:
    """Clear the singleton. Test-only entry point."""
    global _impl
    with _lock:
        _impl = None


__all__ = [
    "EmbeddingProvider",
    "set_embedding_provider",
    "get_embedding_provider",
    "__reset_for_testing",
]
