# ruflo-kb/src/llm/openai_provider.py
"""OpenAI provider — chat completions + embeddings.

The provider is constructed from a :class:`ProviderConfig` and an optional
``client`` (the new ``openai`` SDK style or a fake for tests). Chat calls
go through ``client.chat.completions.create``; the legacy
``/v1/completions`` endpoint is no longer used anywhere.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from .base import LLMProvider, EmbeddingProvider, LLMResponse, EmbeddingResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)

# Reasoning models (MiniMax-M3, DeepSeek-R1, etc.) wrap their output in
# <think>...</think> blocks.  Strip these before the content reaches
# downstream JSON parsers.
_REASONING_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_reasoning(content: str) -> str:
    """Remove ``<think>...</think>`` blocks from a model response."""
    stripped = _REASONING_RE.sub("", content).strip()
    if stripped != content:
        _logger.debug("stripped <think> block from response (%d chars → %d chars)",
                       len(content), len(stripped))
    return stripped


class OpenAIProvider(LLMProvider):
    """OpenAI Provider implementation using the chat completions API."""

    def __init__(
        self,
        config: ProviderConfig,
        model_override: Optional[str] = None,
        *,
        client: Optional[object] = None,
    ):
        self.config = config
        self.base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = config.api_key
        self.model = model_override or config.default_chat_model or "gpt-4o-mini"
        self.timeout_seconds = config.timeout_seconds
        self.extra_headers = dict(config.extra_headers or {})

        # Prefer passing a pre-built SDK client (real or fake). Fall back to
        # constructing a thin httpx-based client on demand when no client is
        # provided. The factory passes a real client when present.
        if client is not None:
            self._client_kind = "sdk"
            self._sdk = client
        else:
            self._client_kind = "httpx"
            self._sdk = None

    # ----- internal helpers ------------------------------------------------
    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h

    async def _post_json(self, url: str, payload: dict, timeout: Optional[float] = None) -> dict:
        effective_timeout = timeout if timeout is not None else self.timeout_seconds
        async with httpx.AsyncClient(timeout=effective_timeout) as sess:
            r = await sess.post(url, headers=self._headers(), json=payload)
            try:
                r.raise_for_status()
            except Exception as e:
                # Attach the response body so the error message is
                # diagnostic even when the provider returns an empty
                # status reason (seen with MiniMax M3).
                body_snippet = (r.text or "")[:200]
                raise RuntimeError(
                    f"HTTP {r.status_code}: {body_snippet}"
                ) from e
            return r.json()

    # ----- chat completion (canonical chat-style contract) -----------------
    async def complete(
        self,
        messages: list[dict],
        *,
        response_format: Optional[dict] = None,
        system: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> LLMResponse:
        """OpenAI chat completion. Sends via /v1/chat/completions.

        - ``system`` is concatenated to the first system-role message
          (OpenAI has no top-level system field); if a system message
          already exists, ``system`` is prepended.
        - ``response_format`` is forwarded verbatim (passed through to the
          API as JSON schema for structured outputs).
        - ``timeout`` overrides the per-call timeout (default 120s).
        """
        msgs = list(messages)

        # Inject top-level system into the first system-role message
        if system:
            sys_idx = next(
                (i for i, m in enumerate(msgs) if m.get("role") == "system"),
                None,
            )
            if sys_idx is not None:
                existing = msgs[sys_idx].get("content", "") or ""
                msgs[sys_idx] = {
                    **msgs[sys_idx],
                    "content": f"{system}\n\n{existing}" if existing else system,
                }
            else:
                msgs = [{"role": "system", "content": system}] + msgs

        model = kwargs.get("model", self.model)
        body: dict = {
            "model": model,
            "messages": msgs,
            "temperature": kwargs.get("temperature", 0.7),
        }
        if kwargs.get("max_tokens") is not None:
            body["max_tokens"] = kwargs["max_tokens"]
        if response_format:
            # Many OpenAI-compatible APIs (MiniMax, DeepSeek, Kimi, GLM,
            # etc.) reject any ``response_format`` parameter — both the
            # legacy ``{"type": "json_object"}`` form and the newer
            # ``{"type": "object", "properties": ...}`` JSON-Schema form
            # — with HTTP 400 "unknown response_format type". The
            # structured-outputs API is OpenAI-specific and not generally
            # replicated by OpenAI-compatible providers.
            #
            # Drop the parameter entirely for non-OpenAI endpoints so the
            # LLM is still expected to return JSON in its content (the
            # system prompt instructs it to) without breaking the request.
            if self.base_url.startswith("https://api.openai.com"):
                body["response_format"] = response_format

        # Two code paths:
        #   - SDK present:  self._sdk.chat.completions.create(...)
        #   - else:         raw httpx POST to {base_url}/chat/completions
        if self._client_kind == "sdk":
            try:
                result = self._sdk.chat.completions.create(**body)
                # openai SDK returns a pydantic-like model; .model_dump() works
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                elif hasattr(result, "to_dict"):
                    data = result.to_dict()
                elif isinstance(result, dict):
                    data = result
                else:
                    # Fallback: pull via attribute access
                    data = {
                        "choices": [
                            {"message": {"content": c.message.content}}
                            for c in result.choices
                        ],
                        "model": getattr(result, "model", model),
                    }
            except Exception as e:
                raise RuntimeError(f"OpenAI complete failed: {e}") from e
        else:
            try:
                data = await self._post_json(
                    f"{self.base_url}/chat/completions", body, timeout=timeout,
                )
            except Exception as e:
                raise RuntimeError(f"OpenAI complete failed: {e}") from e

        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"OpenAI returned malformed response: {e}") from e

        content = _strip_reasoning(content)

        return LLMResponse(
            content=content,
            model=data.get("model", model),
            usage=data.get("usage"),
        )

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Alias for :meth:`complete`."""
        return await self.complete(messages, **kwargs)

    # ----- embeddings ------------------------------------------------------
    async def embed(self, text: str) -> EmbeddingResponse:
        """Legacy single-text embedding (legacy callers)."""
        out = await self._embed_batch([text])
        return out[0]

    async def health_check(self) -> dict:
        """Probe the endpoint and return ``{"ok": bool, "detail": str}``."""
        if self._client_kind == "sdk":
            try:
                await self._sdk.models.list()
                return {"ok": True, "detail": "models.list() OK"}
            except Exception as e:
                return {"ok": False, "detail": f"models.list() failed: {e}"}

        # httpx mode — probe /models via GET (OpenAI-compatible endpoints
        # all support this). Fall back to the base URL if /models 404s.
        try:
            async with httpx.AsyncClient(timeout=10) as sess:
                r = await sess.get(
                    f"{self.base_url}/models",
                    headers={k: v for k, v in self._headers().items()
                             if k.lower() != "content-type"},
                )
                if r.status_code == 200:
                    return {"ok": True, "detail": "/models OK"}
                # Some providers don't expose /models; just checking the
                # base URL is reachable is enough.
                r2 = await sess.get(
                    self.base_url,
                    headers={k: v for k, v in self._headers().items()
                             if k.lower() != "content-type"},
                )
                if r2.status_code < 500:
                    return {"ok": True, "detail": f"base URL reachable (HTTP {r2.status_code})"}
                return {"ok": False, "detail": f"HTTP {r2.status_code}"}
        except Exception as e:
            return {"ok": False, "detail": str(e)}

    async def close(self) -> None:
        """No-op for OpenAI: per-call httpx clients close themselves; SDK
        clients are managed externally."""
        return None


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI dedicated embedding provider (batch).

    When ``config.dimension`` (or constructor ``dimension``) is set and the
    model supports it (``text-embedding-3-*``), the value is forwarded as
    ``dimensions=`` and the returned vector length is validated.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        dimension: Optional[int] = None,
        *,
        config: Optional[ProviderConfig] = None,
        client: Optional[object] = None,
    ):
        # Accept both the legacy direct-arg style and the new ProviderConfig style.
        if config is not None:
            self.api_key = config.api_key or api_key
            self.endpoint = (config.base_url or endpoint or "").rstrip("/")
            self.model = config.default_embedding_model or model
            self.dimension: Optional[int] = (
                dimension if dimension is not None else None
            )
            self.extra_headers = dict(config.extra_headers or {})
            self.timeout_seconds = config.timeout_seconds
        else:
            self.api_key = api_key
            self.endpoint = (endpoint or "").rstrip("/")
            self.model = model
            self.dimension = dimension
            self.extra_headers = {}
            self.timeout_seconds = 60

        self._client_kind = "sdk" if client is not None else "httpx"
        self._sdk = client

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h

    async def embed(self, texts: list[str]) -> list[EmbeddingResponse]:
        """Batch embed. Sends ``dimensions=self.dimension`` when set."""
        body: dict = {"model": self.model, "input": list(texts)}
        if self.dimension is not None:
            body["dimensions"] = self.dimension

        if self._client_kind == "sdk":
            try:
                result = self._sdk.embeddings.create(**body)
            except Exception as e:
                raise RuntimeError(f"OpenAI embedding failed: {e}") from e
            if hasattr(result, "model_dump"):
                data = result.model_dump()
            elif isinstance(result, dict):
                data = result
            else:
                # Pull via attribute access
                data = {
                    "data": [
                        {"embedding": item.embedding}
                        for item in result.data
                    ],
                    "model": getattr(result, "model", self.model),
                }
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as sess:
                r = await sess.post(
                    f"{self.endpoint}/embeddings",
                    headers=self._headers(),
                    json=body,
                )
                r.raise_for_status()
                data = r.json()

        items = data.get("data", [])
        out: list[EmbeddingResponse] = []
        for item in items:
            vec = item.get("embedding") if isinstance(item, dict) else item.embedding
            # Validate returned dimension matches request, if both known
            if self.dimension is not None and len(vec) != self.dimension:
                raise RuntimeError(
                    f"OpenAI returned embedding dimension {len(vec)} "
                    f"but expected {self.dimension}"
                )
            out.append(EmbeddingResponse(embedding=vec, model=self.model))
        return out
