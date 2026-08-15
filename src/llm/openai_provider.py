# ruflo-kb/src/llm/openai_provider.py
"""OpenAI provider — chat completions + embeddings.

The provider is constructed from a :class:`ProviderConfig` and an optional
``client`` (the new ``openai`` SDK style or a fake for tests). Chat calls
go through ``client.chat.completions.create``; the legacy
``/v1/completions`` endpoint is no longer used anywhere.
"""
from __future__ import annotations

import asyncio
import inspect
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

        # Cached response_format compatibility: None = unchecked,
        # True = compatible, False = incompatible (will be skipped).
        self._response_format_ok: bool | None = None

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
        async with httpx.AsyncClient(timeout=effective_timeout, trust_env=False) as sess:
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
            # Auto-downgrade: if startup check found this provider
            # incompatible with the pipeline's non-standard schema, skip
            # response_format entirely.  The JSON schema is already
            # embedded in the prompt, so plain json_object mode is
            # sufficient enforcement everywhere.
            if self._response_format_ok is False:
                response_format = {"type": "json_object"}
            else:
                # Normalize response_format to a shape the endpoint accepts.
                # The pipeline builds a non-standard {"type": "object",
                # "properties": {...}} schema. OpenAI's native structured
                # output uses {"type": "json_schema", "json_schema": {...}};
                # many OpenAI-compatible providers (GLM, DeepSeek, Kimi,
                # MiniMax) accept ONLY {"type": "json_object"} (or text/url/
                # b64_json) and reject the schema form with HTTP 400. The JSON
                # schema is already embedded in the prompt, so downgrading to
                # plain json_object mode is sufficient enforcement everywhere.
                rtype = response_format.get("type")
                if rtype not in ("json_object", "json_schema", "text", "url", "b64_json"):
                    body["response_format"] = {"type": "json_object"}
                else:
                    body["response_format"] = response_format

        # Two code paths:
        #   - SDK present:  await self._sdk.chat.completions.create(...)
        #     (the SDK may be the async ``AsyncOpenAI``/``AsyncAzureOpenAI``
        #     client, in which case the call is awaited; a sync SDK client is
        #     also supported by offloading to a worker thread so the event
        #     loop is never blocked — see Bug #11)
        #   - else:         raw httpx POST to {base_url}/chat/completions
        if self._client_kind == "sdk":
            try:
                create = self._sdk.chat.completions.create
                if inspect.iscoroutinefunction(create):
                    # Async SDK (openai.AsyncOpenAI) — await directly.
                    result = await create(**body)
                else:
                    # Sync SDK (openai.OpenAI) — offload to a worker thread so
                    # the event loop is never blocked (Bug #11).
                    result = await asyncio.to_thread(create, **body)
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

        # finish_reason="length" means the endpoint cut the response off
        # (max_tokens cap). Surface it so JSON callers can retry with a
        # higher max_tokens instead of treating the partial content as a
        # malformed response (batch-10: 11/11 "JSON parse failed" were
        # actually truncated responses).
        try:
            finish_reason = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            finish_reason = None

        return LLMResponse(
            content=content,
            model=data.get("model", model),
            usage=data.get("usage"),
            truncated=finish_reason == "length",
        )

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Alias for :meth:`complete`."""
        return await self.complete(messages, **kwargs)

    # ----- embeddings ------------------------------------------------------
    async def embed(self, text: str) -> EmbeddingResponse:
        """Legacy single-text embedding (legacy callers)."""
        out = await self._embed_batch([text])
        return out[0]

    async def check_response_format(self) -> dict:
        """Probe whether the endpoint accepts the pipeline's non-standard
        ``{"type": "object", "properties": {...}}`` response_format.

        Sends a minimal chat completion with the raw schema shape that the
        pipeline builds. If the provider returns HTTP 400 with
        ``invalid response_format``, the check fails and the user would see
        source-only stub pages after ingestion.

        Caches the result in ``self._response_format_ok`` so the
        ``complete()`` method can auto-skip ``response_format`` on
        incompatible providers.

        Returns ``{"ok": bool, "detail": str}`` matching the
        :meth:`health_check` contract.
        """
        probe_body = {
            "model": self.model,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 1,
            "response_format": {"type": "object", "properties": {"test": {"type": "string"}}},
        }
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as sess:
                r = await sess.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=probe_body,
                )
                if r.status_code == 400 and "response_format" in (r.text or "").lower():
                    self._response_format_ok = False
                    return {
                        "ok": False,
                        "detail": "HTTP 400: provider rejects non-standard response_format "
                                   "(ingestion would produce empty stub pages)",
                    }
                # Any other status (including 200, 401, 404) means the
                # response_format itself wasn't rejected — the endpoint
                # either accepted it or failed for a different reason.
                self._response_format_ok = True
                return {"ok": True, "detail": "response_format accepted"}
        except Exception as e:
            self._response_format_ok = False
            return {"ok": False, "detail": str(e)}

    async def health_check(self) -> dict:
        """Probe the endpoint, check response_format compatibility,
        and return ``{"ok": bool, "detail": str, "response_format_ok": bool}``."""
        # --- Step 1: reachability probe ---
        base_result: dict
        if self._client_kind == "sdk":
            try:
                models_list = self._sdk.models.list()
                if inspect.isawaitable(models_list):
                    await models_list
                else:
                    await asyncio.to_thread(models_list)
                base_result = {"ok": True, "detail": "models.list() OK"}
            except Exception as e:
                base_result = {"ok": False, "detail": f"models.list() failed: {e}"}
        else:
            try:
                async with httpx.AsyncClient(timeout=10, trust_env=False) as sess:
                    r = await sess.get(
                        f"{self.base_url}/models",
                        headers={k: v for k, v in self._headers().items()
                                 if k.lower() != "content-type"},
                    )
                    if r.status_code == 200:
                        base_result = {"ok": True, "detail": "/models OK"}
                    else:
                        r2 = await sess.get(
                            self.base_url,
                            headers={k: v for k, v in self._headers().items()
                                     if k.lower() != "content-type"},
                        )
                        if r2.status_code < 500:
                            base_result = {"ok": True, "detail": f"base URL reachable (HTTP {r2.status_code})"}
                        else:
                            base_result = {"ok": False, "detail": f"HTTP {r2.status_code}"}
            except Exception as e:
                base_result = {"ok": False, "detail": str(e)}

        # --- Step 2: response_format probe (only if reachable) ---
        if base_result.get("ok"):
            rf_result = await self.check_response_format()
            base_result["response_format_ok"] = rf_result.get("ok", False)
            base_result["response_format_detail"] = rf_result.get("detail", "")
        else:
            base_result["response_format_ok"] = False
            base_result["response_format_detail"] = "skipped (provider unreachable)"

        return base_result

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
                create = self._sdk.embeddings.create
                if inspect.iscoroutinefunction(create):
                    result = await create(**body)
                else:
                    result = await asyncio.to_thread(create, **body)
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
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as sess:
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
