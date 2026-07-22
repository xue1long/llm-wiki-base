"""Ollama local LLM provider."""
import logging

import httpx

from .base import LLMProvider, LLMResponse
from .types import ProviderConfig


_logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, config: ProviderConfig, model_override: str | None = None):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.model = model_override or config.default_chat_model
        self.client = httpx.AsyncClient(timeout=config.timeout_seconds)
        # Auto-register for bulk-close on app shutdown (see ProviderRegistry.aclose_all).
        # This prevents the httpx.AsyncClient from leaking when business code
        # creates an OllamaProvider but never calls .close().
        from .registry import ProviderRegistry
        ProviderRegistry._loaded_providers.add(self)

    async def complete(self, prompt, response_format=None, system=None, **kwargs) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {"model": self.model, "messages": messages, "stream": False}
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

    async def embed(self, texts):
        # Convert single string to list to keep the API uniform
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

    async def chat(self, messages, **kwargs):
        """Compatibility wrapper for the LLMProvider.chat contract."""
        body = {"model": self.model, "messages": messages, "stream": False}
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

    async def health_check(self) -> dict:
        try:
            resp = await self.client.get(f"{self.base_url}/api/version", timeout=5)
            resp.raise_for_status()
            return {"reachable": True, "version": resp.json().get("version")}
        except (httpx.HTTPError, httpx.ConnectError) as e:
            return {"reachable": False, "error": str(e)}

    async def close(self) -> None:
        await self.client.aclose()
