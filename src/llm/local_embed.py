"""Local embedding provider wrapping sentence-transformers (gte-small-zh).

This provider works entirely offline — no network, no API key, no proxy.
The default model ``thenlper/gte-small-zh`` is a lightweight Chinese model
and outputs 512-dim vectors.

Usage::

    from src.llm.local_embed import LocalEmbeddingProvider
    provider = LocalEmbeddingProvider()
    responses = await provider.embed(["hello world"])
"""
import logging
import os
from typing import Optional

from .base import EmbeddingProvider, EmbeddingResponse

_logger = logging.getLogger(__name__)

_MODEL_NAME = "thenlper/gte-small-zh"
_EMBEDDING_DIM = 512


class LocalEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that runs sentence-transformers locally.

    Loads the model once on construction (lazy via ``_load_model()``).
    All subsequent ``embed()`` calls reuse the same model instance, so
    there is no per-call overhead beyond the forward pass.

    The model is loaded from HuggingFace cache
    (``~/.cache/huggingface/hub/``) so it works offline after the first
    download.
    """

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or os.environ.get(
            "RUFLO_LOCAL_EMBEDDING_MODEL", _MODEL_NAME
        )
        self._model = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self):
        """Import sentence-transformers and load the model (lazy, once)."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc

        _logger.info("Loading local embedding model %s ...", self._model_name)
        self._model = SentenceTransformer(self._model_name)
        _logger.info(
            "Local embedding model loaded: %s (dim=%d)",
            self._model_name,
            self._model.get_sentence_embedding_dimension(),
        )

    # ------------------------------------------------------------------
    # EmbeddingProvider interface
    # ------------------------------------------------------------------

    async def embed(self, texts: list[str]) -> list[EmbeddingResponse]:
        """Embed a list of texts, returning one vector per input.

        The forward pass is CPU-bound, so it is offloaded to a thread
        via ``asyncio.to_thread`` to avoid blocking the event loop.
        """
        self._load_model()
        model = self._model

        import asyncio

        # sentence_transformers.encode runs synchronously on CPU
        vectors = await asyncio.to_thread(model.encode, texts, normalize_embeddings=True)

        return [
            EmbeddingResponse(embedding=vec.tolist(), model=self._model_name)
            for vec in vectors
        ]

    async def health_check(self) -> dict:
        """Local provider is always healthy — no network dependency."""
        return {"ok": True, "detail": "local sentence-transformers"}

    async def close(self) -> None:
        """Release the model reference (no special cleanup needed)."""
        self._model = None
        _logger.info("Local embedding model released.")


__all__ = ["LocalEmbeddingProvider", "_EMBEDDING_DIM"]
