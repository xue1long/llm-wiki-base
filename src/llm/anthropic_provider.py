# ruflo-kb/src/llm/anthropic_provider.py
"""Anthropic Claude provider — uses the messages API with top-level ``system``.

Default base URL is ``https://api.anthropic.com/v1`` (registry default).
System-role messages are lifted to the top-level ``system`` field rather than
silently dropped (which was the previous behaviour).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .base import LLMProvider, LLMResponse, EmbeddingResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


# Per Anthropic docs: messages endpoint lives under /v1/messages. The default
# base URL is the public api endpoint with the /v1 prefix included so that
# `{base_url}/messages` is the correct call target.
_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation."""

    def __init__(
        self,
        config: ProviderConfig,
        model_override: Optional[str] = None,
        *,
        client: Optional[object] = None,
    ):
        self.config = config
        self.base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.api_key = config.api_key
        self.model = model_override or config.default_chat_model or "claude-haiku-4-5"
        self.timeout_seconds = config.timeout_seconds
        self.extra_headers = dict(config.extra_headers or {})

        self._client_kind = "sdk" if client is not None else "httpx"
        self._sdk = client
        self.client = client

    def _headers(self) -> dict:
        h = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        h.update(self.extra_headers)
        return h

    async def _post_json(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as sess:
            r = await sess.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    async def complete(
        self,
        messages: list[dict],
        *,
        response_format: Optional[dict] = None,
        system: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """Anthropic message completion.

        Splits ``messages`` into a top-level ``system`` (joined ``\\n\\n``) and
        a ``messages`` array with no ``system``-role entries. Per the API
        contract, ``system`` lives at the root of the request body.
        """
        sys_parts: list[str] = []
        chat_messages: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                if content:
                    sys_parts.append(content)
            else:
                chat_messages.append({"role": role, "content": content})

        # Prepend explicit `system=` kwarg if provided
        if system:
            sys_parts.insert(0, system)

        model = kwargs.get("model", self.model)
        body: dict = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": kwargs.get("max_tokens", 1024),
            "temperature": kwargs.get("temperature", 0.7),
        }
        if sys_parts:
            body["system"] = "\n\n".join(sys_parts)
        # Anthropic doesn't natively support response_format; ignore or pass as metadata
        if response_format:
            # Best-effort: embed as a metadata hint. Real Anthropic JSON outputs use tool use.
            body["metadata"] = {"response_format": True}

        if self._client_kind == "sdk":
            try:
                result = self._sdk.messages.create(**body)
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                elif isinstance(result, dict):
                    data = result
                else:
                    blocks = getattr(result, "content", None) or []
                    text_parts = []
                    for block in blocks:
                        if getattr(block, "type", None) == "text":
                            text_parts.append(getattr(block, "text", ""))
                    data = {
                        "content": [{"text": "".join(text_parts), "type": "text"}],
                        "model": getattr(result, "model", model),
                        "usage": getattr(result, "usage", None),
                    }
            except Exception as e:
                raise RuntimeError(f"Anthropic complete failed: {e}")
        else:
            try:
                data = await self._post_json(f"{self.base_url}/messages", body)
            except Exception as e:
                raise RuntimeError(f"Anthropic complete failed: {e}")

        # Anthropic returns ``content`` as a list of blocks. ``text`` blocks carry
        # the message text; concatenate them.
        try:
            blocks = data.get("content") or []
            text_parts = [
                b.get("text", "") for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            content = "".join(text_parts)
        except AttributeError:
            content = ""

        usage_obj = data.get("usage") or {}
        usage_in = usage_obj.get("input_tokens") if isinstance(usage_obj, dict) else None
        usage_out = usage_obj.get("output_tokens") if isinstance(usage_obj, dict) else None
        usage = None
        if usage_in is not None or usage_out is not None:
            usage = {
                "input_tokens": usage_in,
                "output_tokens": usage_out,
            }

        return LLMResponse(
            content=content,
            model=data.get("model", model),
            usage=usage,
        )

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """Alias for :meth:`complete`."""
        return await self.complete(messages, **kwargs)

    async def embed(self, text: str) -> EmbeddingResponse:
        """Anthropic doesn't provide a public embeddings API."""
        raise NotImplementedError("Anthropic does not support embeddings API")

    async def health_check(self) -> dict:
        """Probe via SDK; return ``{"ok": bool, "detail": str}`` (audit I2).

        Standardised dict contract shared by every LLM provider so callers
        can render the detail string in logs / CLI.
        """
        if self._client_kind != "sdk":
            return {"ok": True, "detail": "no SDK client to probe"}
        try:
            # anthropic SDK doesn't have a generic models.list; use a minimal
            # messages probe via /v1/models which IS available on the API
            await self._sdk.models.list(limit=1)  # type: ignore[attr-defined]
            return {"ok": True, "detail": "models.list() OK"}
        except Exception as e:
            return {"ok": False, "detail": f"models.list() failed: {e}"}

    async def close(self) -> None:
        """No-op for Anthropic — SDK clients managed externally."""
        return None
