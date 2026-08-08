"""Ollama local LLM provider.

Cleanup (Task 3, I-llm-7): one ``httpx.AsyncClient`` per ``base_url`` is
cached process-globally to prevent resource leaks when many provider
instances are created. ``close()`` closes the cached client exactly once
(idempotent across multiple instances sharing the same URL).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import httpx

from .base import LLMProvider, LLMResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


# Module-level cache: base_url -> httpx.AsyncClient (one per process).
# Cleared on close(); shared across all OllamaProvider instances with the
# same base URL. Keyed by base_url so different endpoints stay isolated.
_CLIENT_CACHE: dict[str, httpx.AsyncClient] = {}

# Reference count: base_url -> int.  Tracks how many active OllamaProvider
# instances reference each cached client so close() only releases the
# underlying transport when the last instance is done (Bug #13).
_CLIENT_REFCOUNT: dict[str, int] = {}

# Thread-safety lock for the module-level cache and refcount dicts.
# Protects against concurrent access from multiple threads (Bug #12).
_CLIENT_LOCK = threading.Lock()

# Track the event-loop id each cached client was created on.  When
# asyncio.run() creates a fresh loop (common in tests and CLI scripts),
# a client bound to the old loop is unusable — we detect the mismatch
# and recreate.
_CLIENT_LOOP_IDS: dict[str, int] = {}


def _get_or_create_client(base_url: str, timeout: float, headers: dict) -> httpx.AsyncClient:
    """Return a cached AsyncClient, recreating it if the event loop changed.

    When ``asyncio.run()`` is called repeatedly (tests, CLI scripts), each
    invocation creates a fresh event loop.  An ``httpx.AsyncClient`` created
    on loop N becomes unusable after loop N closes — subsequent ``await
    client.post(...)`` calls raise ``RuntimeError("Event loop is closed")``.

    We detect the mismatch by comparing the identity of the current default
    event loop with the one stored at client-creation time.  On loop change,
    the old client is closed and a fresh one is created.

    The whole cache/lookup is guarded by :data:`_CLIENT_LOCK` so concurrent
    access from multiple threads is safe (Bug #12).
    """
    import asyncio

    with _CLIENT_LOCK:
        cached = _CLIENT_CACHE.get(base_url)
        if cached is not None:
            try:
                current_loop_id = id(asyncio.get_event_loop())
            except RuntimeError:
                current_loop_id = 0
            cached_loop_id = _CLIENT_LOOP_IDS.get(base_url)
            if cached_loop_id and cached_loop_id != current_loop_id:
                # Loop changed — old client is bound to a dead loop.
                try:
                    asyncio.get_event_loop().run_until_complete(cached.aclose())
                except Exception:
                    pass
                cached = None

        if cached is None:
            cached = httpx.AsyncClient(timeout=timeout, headers=headers)
            _CLIENT_CACHE[base_url] = cached
            try:
                _CLIENT_LOOP_IDS[base_url] = id(asyncio.get_event_loop())
            except RuntimeError:
                pass

        # Increment the reference count for this base_url.
        _CLIENT_REFCOUNT[base_url] = _CLIENT_REFCOUNT.get(base_url, 0) + 1

        return cached


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

        # Reuse one cached AsyncClient per base_url.  When the event loop
        # changes (asyncio.run() in tests/CLI scripts), the old client is
        # automatically replaced with a fresh one on the current loop.
        self.client = _get_or_create_client(
            self.base_url,
            timeout=config.timeout_seconds,
            headers=dict(self.extra_headers or {}),
        )

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

        # Respect the configured context window (the Ollama default of 4096
        # tokens is too small for pipeline prompts which routinely exceed
        # 8K tokens).  Read from the per-model ModelInfo; fall back to a
        # safe default of 8192 when nothing is configured.
        model_info = self.config.models.get(self.model) if self.config.models else None
        ctx = (
            model_info.context_window
            if model_info and model_info.context_window
            else 8192
        )
        # Always send num_ctx when explicitly configured — allows both
        # increasing (for long prompts) and decreasing (to save VRAM).
        if ctx:
            body.setdefault("options", {})["num_ctx"] = ctx

        resp = await self.client.post(f"{self.base_url}/api/chat", json=body)
        if not resp.is_success:
            _logger.error(
                "[Ollama] HTTP %d from %s/api/chat (model=%s, body_size=%d): %s",
                resp.status_code, self.base_url, self.model,
                len(str(body)), resp.text[:500],
            )
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
        """Release this instance's reference to the cached ``AsyncClient``.

        The cached client is only closed (its transport released) when the
        last referencing instance calls ``close()`` — guarded by a reference
        count keyed by ``base_url`` (Bug #13).  Idempotent: calling
        ``close()`` again on the same instance (after the cache was already
        cleared by the last close) is a no-op.
        """
        with _CLIENT_LOCK:
            remaining = _CLIENT_REFCOUNT.get(self.base_url, 0)
            if remaining <= 1:
                # This is the last reference — drop the refcount and evict
                # the cached client so it is closed exactly once.
                _CLIENT_REFCOUNT.pop(self.base_url, None)
                client = _CLIENT_CACHE.pop(self.base_url, None)
            else:
                _CLIENT_REFCOUNT[self.base_url] = remaining - 1
                client = None

        if client is not None:
            await client.aclose()
