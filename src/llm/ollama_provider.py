"""Ollama local LLM provider.

Cleanup (Task 3, I-llm-7): one ``httpx.AsyncClient`` per ``base_url`` is
cached process-globally to prevent resource leaks when many provider
instances are created. ``close()`` closes the cached client exactly once
(idempotent across multiple instances sharing the same URL).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .base import LLMProvider, LLMResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


# Module-level cache: base_url -> httpx.AsyncClient (one per process).
# Cleared on close(); shared across all OllamaProvider instances with the
# same base URL. Keyed by base_url so different endpoints stay isolated.
_CLIENT_CACHE: dict[str, httpx.AsyncClient] = {}


class OllamaProvider(LLMProvider):
    """Ollama provider — uses native ``/api/chat`` and ``/api/embeddings``."""

    # Exposed for tests via ``OllamaProvider._client_cache``
    _client_cache = _CLIENT_CACHE

    def __init__(
        self,
        config: ProviderConfig,
        model_override: Optional[str] = None,
    ):
        self.config = config
        self.base_url = (config.base_url or "http://127.0.0.1:11434").rstrip("/")
        self.model = model_override or config.default_chat_model
        self.extra_headers = dict(config.extra_headers or {})

        # Reuse one cached AsyncClient per base_url. If a key exists, share
        # it; otherwise create and cache a fresh one.
        cached = _CLIENT_CACHE.get(self.base_url)
        if cached is None:
            headers = dict(self.extra_headers)
            cached = httpx.AsyncClient(
                timeout=config.timeout_seconds,
                headers=headers,
            )
            _CLIENT_CACHE[self.base_url] = cached
        self.client = cached

        # Auto-register for bulk-close on app shutdown (see ProviderRegistry.aclose_all).
        from .registry import ProviderRegistry
        ProviderRegistry._loaded_providers.add(self)

    async def complete(
        self,
        messages: list[dict],
        *,
        response_format: Optional[dict] = None,
        system: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        body: dict = {"model": self.model, "messages": list(messages), "stream": False}
        if system:
            body["messages"] = [{"role": "system", "content": system}] + body["messages"]
        if response_format:
            body["format"] = "json"

        resp = await self.client.post(f"{self.base_url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["message"]["content"],
            model=self.model,
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        )

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Alias for :meth:`complete`."""
        return await self.complete(messages, **kwargs)

    async def embed(self, texts) -> list[list[float]]:
        """Legacy single/batch embedding API; returns ``list[list[float]]``
        to match the legacy ``embedding``-path contract."""
        if isinstance(texts, str):
            texts = [texts]
        embeddings: list[list[float]] = []
        embed_model = self.config.default_embedding_model
        for text in texts:
            resp = await self.client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": embed_model, "prompt": text},
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
        return embeddings

    async def health_check(self) -> dict:
        """Probe ``/api/version`` and return ``{"ok": bool, "detail": str, "version": str|None}``.

        Standardised shape (audit I2): every provider returns the same
        ``{"ok", "detail", ...}`` dict so the server lifespan, CLI,
        and tests can consume ``health_check()`` uniformly.
        """
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/version", timeout=5,
            )
            resp.raise_for_status()
            return {"ok": True, "detail": "reachable", "version": resp.json().get("version")}
        except (httpx.HTTPError, httpx.ConnectError) as e:
            return {"ok": False, "detail": str(e), "version": None}

    async def close(self) -> None:
        """Close the cached ``AsyncClient`` exactly once per base_url.

        Idempotent: if ``close()`` is called a second time on a different
        instance sharing the same URL (or after the cache was cleared by
        a previous close), this is a no-op.
        """
        client = _CLIENT_CACHE.pop(self.base_url, None)
        if client is None:
            return
        await client.aclose()
