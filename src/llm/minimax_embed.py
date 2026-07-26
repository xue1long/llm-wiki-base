"""MiniMax embedding provider (native API, not OpenAI-compatible).

MiniMax's ``/embeddings`` endpoint differs from OpenAI's:
* request uses ``texts`` (a list) instead of OpenAI's ``input``;
* response wraps vectors under ``vectors`` (not ``data``);
* a non-zero ``base_resp.status_code`` signals an error.

The ``embo-01`` model outputs 1536-dimensional vectors, which matches the
LanceDB schema used by ruflo-kb — so no index rebuild is required.
"""
import logging
from typing import List, Optional

import httpx

from .base import EmbeddingResponse

_logger = logging.getLogger(__name__)

_EMBED_PATH = "/embeddings"


class MiniMaxEmbeddingProvider:
    """Embedding provider backed by MiniMax's native embeddings API."""

    def __init__(
        self,
        api_key: str = "",
        endpoint: str = "https://api.minimax.chat/v1",
        model: str = "embo-01",
        timeout_seconds: int = 60,
    ):
        self.api_key = api_key
        self.endpoint = (endpoint or "https://api.minimax.chat/v1").rstrip("/")
        self.model = model or "embo-01"
        self.timeout_seconds = timeout_seconds

    async def embed(self, texts) -> List[EmbeddingResponse]:
        """Embed a list of strings; returns ``list[EmbeddingResponse]``."""
        if isinstance(texts, str):
            texts = [texts]
        texts = list(texts)
        url = f"{self.endpoint}{_EMBED_PATH}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # `type`: "db" for document/passage embedding, "query" for queries.
        # We default to "db" since the KB embeds stored note chunks.
        body = {"model": self.model, "texts": texts, "type": "db"}
        # Floor the timeout so batch embedding of many chunks doesn't trip
        # httpx's ReadTimeout on slower responses.
        _timeout = self.timeout_seconds or 0
        if _timeout < 180:
            _timeout = 180
        async with httpx.AsyncClient(timeout=_timeout) as sess:
            r = await sess.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        base = data.get("base_resp") or {}
        if base.get("status_code", 0) != 0:
            raise RuntimeError(
                f"MiniMax embedding failed: {base.get('status_msg', 'unknown error')}"
            )
        vectors = data.get("vectors") or []
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"MiniMax embedding returned {len(vectors)} vectors "
                f"for {len(texts)} texts"
            )
        return [EmbeddingResponse(embedding=v, model=self.model) for v in vectors]
